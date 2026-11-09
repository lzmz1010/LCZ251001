"""MCP Server 管理器：读取配置、连接并发现工具、注册进工具注册表。

负责在内部维护“暴露给大模型的工具名称 → (MCP Server 名称, 原始工具名)”
的映射，并在出现名称冲突时给暴露名称增加服务器前缀。
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Pattern

from core.mcp.client import McpClient
from core.mcp.config import McpConfig, McpServerConfig
from core.mcp.tool import McpTool, build_parameters
from core.tools.registry import ToolRegistry

#: 工具名称可用的字符（OpenAI function name 仅允许字母、数字、下划线、连字符）。
_NAME_RE: Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]+$")


def _slug(server_name: str) -> str:
    """把服务器名称规范化为可用的工具名片段（否则替换为下划线）。"""
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", server_name)
    return slug.strip("_-") or "mcp"


class McpManager:
    """管理多个 MCP Server 并注册其工具。"""

    def __init__(self, default_timeout: float = 60.0, connect_timeout: float = 30.0) -> None:
        self._default_timeout = default_timeout
        self._connect_timeout = connect_timeout
        self._clients: dict[str, McpClient] = {}
        #: 暴露名称 → (服务器名称, 原始工具名称)
        self._mapping: dict[str, tuple[str, str]] = {}
        #: 连接/发现阶段的错误信息（不阻断其他工具，仅提示）。
        self._errors: list[str] = []

    @property
    def mapping(self) -> dict[str, tuple[str, str]]:
        """暴露给大模型的工具名称与其来源的映射。"""
        return dict(self._mapping)

    @property
    def errors(self) -> list[str]:
        """启动阶段的 MCP 错误提示。"""
        return list(self._errors)

    @property
    def clients(self) -> dict[str, McpClient]:
        """已成功连接的服务器名称 → 客户端。"""
        return dict(self._clients)

    def connected_servers(self) -> list[str]:
        """已成功连接的服务器名称（按配置顺序保持稳定）。"""
        return list(self._clients)

    def server_tools(self) -> dict[str, list[str]]:
        """返回 服务器名称 → 该服务器暴露给模型的工具名列表。"""
        grouped: dict[str, list[str]] = {}
        for exposed, (server_name, _original) in self._mapping.items():
            grouped.setdefault(server_name, []).append(exposed)
        return {name: grouped.get(name, []) for name in self.connected_servers()}

    def close_all(self) -> None:
        """关闭全部 MCP 连接。"""
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    async def register_async(self, registry: ToolRegistry, config: McpConfig) -> None:
        """在后台线程里执行 ``register``（不阻塞前端事件循环），供异步加载使用。"""
        await asyncio.to_thread(self.register, registry, config)

    def register(self, registry: ToolRegistry, config: McpConfig) -> None:
        """连接各 MCP Server、发现工具并注册进 ``registry``。"""
        used_names: set[str] = set(registry.names)
        for server in config.servers:
            try:
                client = McpClient(
                    server,
                    default_timeout=self._default_timeout,
                    connect_timeout=self._connect_timeout,
                )
                client.connect()
                tools = client.list_tools_sync()
            except Exception as exc:  # noqa: BLE001 - 单服务器失败不影响其他工具
                self._errors.append(
                    f"MCP Server '{server.name}' ({server.url}) 连接/发现工具失败: {exc}"
                )
                self._print_error(
                    f"无法接入 MCP Server '{server.name}' ({server.url}): {exc}"
                )
                continue

            self._clients[server.name] = client
            for remote_tool in tools:
                original_name = getattr(remote_tool, "name", "") or ""
                if not original_name:
                    continue
                exposed = self._assign_used_name(server.name, original_name, used_names)
                used_names.add(exposed)
                self._mapping[exposed] = (server.name, original_name)
                registry.register(
                    McpTool(
                        client,
                        name=exposed,
                        original_name=original_name,
                        description=getattr(remote_tool, "description", "") or "",
                        parameters=build_parameters(
                            getattr(remote_tool, "input_schema", None)
                            or getattr(remote_tool, "inputSchema", None)
                        ),
                    )
                )
                self._print_info(
                    f"已接入 MCP 工具: '{server.name}'::{original_name} "
                    f"(暴露名 '{exposed}')"
                )

    @staticmethod
    def _assign_used_name(
        server_name: str, original_name: str, used_names: set[str]
    ) -> str:
        """返回一个不与现有名称冲突的暴露名；冲突时加服务器前缀。"""
        candidate = original_name
        if candidate in used_names:
            candidate = f"{_slug(server_name)}_{original_name}"
        counter = 1
        while candidate in used_names:
            candidate = f"{_slug(server_name)}_{original_name}_{counter}"
            counter += 1
        return candidate

    @staticmethod
    def _print_error(message: str) -> None:
        print(f"[MCP] {message}", file=sys.stderr)

    @staticmethod
    def _print_info(message: str) -> None:
        print(f"[MCP] {message}", file=sys.stderr)
