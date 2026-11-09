"""单个 MCP Server 的客户端。

基于 MCP Python SDK（``mcp``）的标准接口实现，使用 Streamable HTTP 协议。

设计要点：
- 为了兼容 xAgent 现有的同步/异步混合调用方式，每个 ``McpClient`` 独自持有一个
  后台线程 + 独立事件循环，长期保活握手后的 ``ClientSession``。这样无论是在
  组装阶段的同步代码，还是在 Agent 的异步事件循环里调用工具，都不会因为
  “事件循环嵌套”而冲突，也不必每调用一次就重新握手。
- 同步方法（供启动装配阶段用）与异步方法（供 Agent 工具调用用）共用同一个会话。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable

import httpx

from core.errors import ToolError
from core.mcp.config import McpServerConfig

DEFAULT_TIMEOUT = 60.0
CONNECT_TIMEOUT = 30.0


class McpClientError(ToolError):
    """连接或调用 MCP Server 失败。"""


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    """在后台线程里长期运行事件循环。"""
    asyncio.set_event_loop(loop)
    loop.run_forever()


class McpClient:
    """连接单个 MCP Server 并在其上发现/调用工具的客户端。"""

    def __init__(
        self,
        server: McpServerConfig,
        default_timeout: float = DEFAULT_TIMEOUT,
        connect_timeout: float = CONNECT_TIMEOUT,
    ) -> None:
        self._server = server
        self._default_timeout = default_timeout
        self._connect_timeout = connect_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: Any | None = None
        self._transport: Any | None = None

    @property
    def server_name(self) -> str:
        """MCP Server 名称（取自 ``.mcp.json``）。"""
        return self._server.name

    @property
    def url(self) -> str:
        """MCP Server 地址。"""
        return self._server.url

    @property
    def is_connected(self) -> bool:
        """会话是否已建立。"""
        return self._session is not None

    # ---------- 会话生命周期 ----------

    def connect(self) -> None:
        """建立连接并完成 initialize 握手（同步阻塞，供启动装配阶段调用）。"""
        self._ensure_loop()
        try:
            self._wait(self._connect_async, timeout=self._connect_timeout)
        except Exception as exc:  # noqa: BLE001 - 统一包装为客户端错误
            raise McpClientError(
                f"连接 MCP Server '{self._server.name}' 失败: {exc}"
            ) from exc

    def close(self) -> None:
        """关闭与 MCP Server 的连接。"""
        if self._loop is None:
            return
        try:
            self._wait(self._disconnect_async, timeout=5.0)
        except Exception:  # noqa: BLE001 - 关闭失败不影响主流程
            pass
        self._session = None
        self._transport = None

    # ---------- 工具发现 ----------

    def list_tools_sync(self) -> list[Any]:
        """同步调用 ``list_tools()``，返回 MCP 工具对象列表。"""
        return self._wait(self._list_tools_async)

    async def list_tools_async(self) -> list[Any]:
        """异步调用 ``list_tools()``，返回 MCP 工具对象列表。"""
        return await self._await_submit(self._list_tools_async)

    # ---------- 工具调用 ----------

    def call_tool_sync(
        self, name: str, arguments: dict[str, Any] | None
    ) -> Any:
        """同步调用某个 MCP 工具，返回 ``CallToolResult``。"""
        return self._wait(
            lambda: self._call_tool_async(name, arguments or {})
        )

    async def call_tool_async(
        self, name: str, arguments: dict[str, Any] | None
    ) -> Any:
        """异步调用某个 MCP 工具，返回 ``CallToolResult``。"""
        return await self._await_submit(
            lambda: self._call_tool_async(name, arguments or {})
        )

    # ---------- 后台线程 / 事件循环调度 ----------

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_run_loop,
            args=(loop,),
            name=f"mcp-{self._server.name}",
            daemon=True,
        )
        thread.start()
        self._loop = loop
        self._thread = thread

    def _submit(self, factory: Callable[[], Any]) -> "asyncio.Future[Any]":
        """把协程工厂提交到后台事件循环，返回 Future。"""
        if self._loop is None:
            raise McpClientError(
                f"MCP Server '{self._server.name}' 尚未连接，无法调用工具"
            )
        return asyncio.run_coroutine_threadsafe(factory(), self._loop)

    def _wait(
        self, factory: Callable[[], Any], timeout: float | None = None
    ) -> Any:
        """同步等待后台循环中协程的返回结果。"""
        fut = self._submit(factory)
        timeout = timeout or self._server.timeout or self._default_timeout
        return fut.result(timeout=timeout)

    async def _await_submit(
        self, factory: Callable[[], Any]
    ) -> Any:
        """异步等待后台循环中协程的返回结果。"""
        fut = self._submit(factory)
        return await asyncio.wrap_future(fut)

    # ---------- 后台事件循环内运行的协程 ----------

    async def _connect_async(self) -> None:
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        kwargs: dict[str, Any] = {}
        if self._server.headers or self._server.timeout is not None:
            timeout = (
                httpx.Timeout(self._server.timeout)
                if self._server.timeout is not None
                else None
            )
            kwargs["http_client"] = httpx.AsyncClient(
                headers=self._server.headers, timeout=timeout
            )
        self._transport = streamable_http_client(self._server.url, **kwargs)
        read, write = await self._transport.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self._session = session

    async def _disconnect_async(self) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                pass
            self._session = None
        if self._transport is not None:
            try:
                await self._transport.__aexit__(None, None, None)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                pass
            self._transport = None

    async def _list_tools_async(self) -> list[Any]:
        if self._session is None:
            raise McpClientError(
                f"MCP Server '{self._server.name}' 已断开连接"
            )
        result = await self._session.list_tools()
        return list(result.tools)

    async def _call_tool_async(
        self, name: str, arguments: dict[str, Any]
    ) -> Any:
        if self._session is None:
            raise McpClientError(
                f"MCP Server '{self._server.name}' 已断开连接"
            )
        result = await self._session.call_tool(name, arguments or {})
        return result
