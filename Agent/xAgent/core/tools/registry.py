"""工具注册表：负责注册、查询与安全地执行工具。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from core.errors import ToolError
from core.tools.base import Tool, ToolSpec


@dataclass(frozen=True)
class ToolResult:
    """工具执行结果。"""

    content: str
    is_error: bool = False


class ToolRegistry:
    """工具集合，core 与前端都通过它访问工具。"""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> Tool:
        """注册一个工具，重复注册会报错。"""
        name = tool.spec().name
        if not name:
            raise ValueError("工具必须提供 name")
        if name in self._tools:
            raise ValueError(f"工具 {name} 已注册")
        self._tools[name] = tool
        return tool

    def decorator(self, func: Callable[..., Any], **kwargs: Any) -> Tool:
        """以装饰器形式注册普通函数。"""
        tool = Tool.from_function(func, **kwargs)
        self.register(tool)
        return tool

    def get(self, name: str) -> Tool | None:
        """按名称查找工具。"""
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        """已注册的工具名称。"""
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        """全部工具描述。"""
        return [tool.spec() for tool in self._tools.values()]

    def to_openai_schema(self) -> list[dict[str, Any]]:
        """全部工具的 OpenAI function calling 定义。"""
        return [spec.to_openai_schema() for spec in self.specs()]

    def _prepare(self, name: str, raw_arguments: str) -> tuple[Tool | None, dict[str, Any] | ToolResult]:
        """定位工具并校验参数，返回 (tool, 参数字典)；校验失败时返回 (None, ToolResult)。"""
        tool = self._tools.get(name)
        if tool is None:
            return None, ToolResult(content=f"未知工具: {name}", is_error=True)

        try:
            arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except json.JSONDecodeError as exc:
            return None, ToolResult(
                content=f"工具参数不是合法的 JSON: {exc}", is_error=True
            )
        if not isinstance(arguments, dict):
            return None, ToolResult(content="工具参数必须是 JSON 对象", is_error=True)

        spec = tool.spec()
        missing = [
            p.name for p in spec.parameters if p.required and p.name not in arguments
        ]
        if missing:
            return None, ToolResult(
                content=f"缺少参数: {', '.join(missing)}", is_error=True
            )

        return tool, arguments

    @staticmethod
    def _wrap_error(exc: Exception) -> ToolResult:
        """把工具异常转换为回传给模型的结果。"""
        if isinstance(exc, ToolError):
            return ToolResult(content=str(exc), is_error=True)
        return ToolResult(content=f"工具执行失败: {exc}", is_error=True)

    async def execute_async(self, name: str, raw_arguments: str = "") -> ToolResult:
        """异步执行工具，永远返回结果对象而不抛出异常。"""
        tool, arguments = self._prepare(name, raw_arguments)
        if arguments is None or isinstance(arguments, ToolResult):
            return arguments  # type: ignore[return-value] - 已携带校验结果

        try:
            return ToolResult(content=str(await tool.invoke_async(**arguments)))
        except Exception as exc:  # noqa: BLE001 - 工具异常需要回传给模型
            return self._wrap_error(exc)

    def execute(self, name: str, raw_arguments: str = "") -> ToolResult:
        """同步执行工具，永远返回结果对象而不抛出异常。"""
        tool, arguments = self._prepare(name, raw_arguments)
        if arguments is None or isinstance(arguments, ToolResult):
            return arguments  # type: ignore[return-value] - 已携带校验结果

        try:
            return ToolResult(content=str(tool.invoke(**arguments)))
        except Exception as exc:  # noqa: BLE001 - 工具异常需要回传给模型
            return self._wrap_error(exc)
