"""MCP 工具适配器。

把一个远程 MCP 工具包装成 xAgent 的 ``Tool``，使其能像本地工具一样
通过 Function Calling 被大模型调用，并把文本、结构化数据与错误信息
统一转回给大模型。
"""

from __future__ import annotations

import json
from typing import Any

from core.errors import ToolError
from core.mcp.client import McpClient
from core.tools.base import Tool, ToolParameter

_TYPE_MAP = {
    "string": "string",
    "object": "object",
    "array": "array",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "null": "string",
}


def _map_type(raw_type: Any) -> str:
    return _TYPE_MAP.get(raw_type, "string")


def build_parameters(input_schema: Any) -> tuple[ToolParameter, ...]:
    """把 MCP 工具参数的 JSON Schema 转成 ``ToolParameter`` 列表。"""
    schema = input_schema if isinstance(input_schema, dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required_names = set(schema.get("required") or [])

    parameters: list[ToolParameter] = []
    for param_name, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        param_type = _map_type(prop.get("type", "string"))
        items: str | None = None
        if param_type == "array":
            items_schema = prop.get("items")
            if isinstance(items_schema, dict):
                items = _map_type(items_schema.get("type", "string"))
        enum = prop.get("enum")
        parameters.append(
            ToolParameter(
                name=param_name,
                type=param_type,
                description=prop.get("description", ""),
                required=param_name in required_names,
                enum=tuple(enum) if isinstance(enum, (list, tuple)) else None,
                items=items,
            )
        )
    return tuple(parameters)


def _format_result(result: Any) -> str:
    """把 MCP ``CallToolResult`` 的文本、结构化数据转换成可读字符串。"""
    lines: list[str] = []
    for block in getattr(result, "content", None) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", "")
            if text:
                lines.append(text)
        elif block_type == "image":
            lines.append("[图片数据（文本通道无法直接展示）]")
        else:
            try:
                rendered = str(block).strip()
                if rendered:
                    lines.append(rendered)
            except Exception:  # noqa: BLE001
                lines.append("[无法渲染的结构化内容]")

    # 已有文本内容时不再重复拼接结构化数据（多数服务器 text 与 structured 内容相同）
    structured = getattr(result, "structured_content", None)
    if structured is not None and not lines:
        try:
            data = (
                structured.get_python()
                if hasattr(structured, "get_python")
                else structured
            )
        except Exception:  # noqa: BLE001
            data = structured
        try:
            lines.append(
                json.dumps(data, ensure_ascii=False, indent=2, default=str)
            )
        except (TypeError, ValueError):
            lines.append(str(data))

    text = "\n".join(lines).strip()
    return text or "(MCP 工具返回空结果)"


class McpTool(Tool):
    """把远程 MCP 工具包装成本地 ``Tool`` 的适配器。"""

    name: str = ""
    description: str = ""
    parameters: tuple[ToolParameter, ...] = ()

    def __init__(
        self,
        client: McpClient,
        *,
        name: str,
        original_name: str,
        description: str = "",
        parameters: tuple[ToolParameter, ...] = (),
    ) -> None:
        self.name = name
        self.original_name = original_name
        self.description = (
            description
            or f"MCP Server '{client.server_name}' 提供的工具 {original_name}"
        )
        self.parameters = parameters
        self._client = client

    @property
    def server_name(self) -> str:
        """对应的 MCP Server 名称。"""
        return self._client.server_name

    def invoke(self, **kwargs: Any) -> str:
        """同步调用远程 MCP 工具。"""
        result = self._client.call_tool_sync(self.original_name, kwargs)
        return self._resolve(result)

    async def invoke_async(self, **kwargs: Any) -> str:
        """异步调用远程 MCP 工具。"""
        result = await self._client.call_tool_async(self.original_name, kwargs)
        return self._resolve(result)

    @staticmethod
    def _resolve(result: Any) -> str:
        """把 ``CallToolResult`` 解析成字符串；服务器报错时抛错以标记工具失败。"""
        text = _format_result(result)
        if getattr(result, "is_error", False):
            raise ToolError(f"[MCP 错误] {text}")
        return text
