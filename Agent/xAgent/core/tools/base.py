"""工具抽象层。

工具是 core 对外暴露能力的统一形式：
- ``ToolParameter`` 描述单个入参（生成 OpenAI function schema）。
- ``ToolSpec``     描述工具整体。
- ``Tool``         工具基类，子类实现 ``invoke``。
- ``FunctionTool`` 把普通函数包装成工具，方便快速扩展。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Iterable


@dataclass(frozen=True)
class ToolParameter:
    """工具的一个入参。"""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    enum: tuple[str, ...] | None = None
    items: str | None = None

    def to_schema(self) -> dict[str, Any]:
        """转换为 JSON Schema 片段。"""
        schema: dict[str, Any] = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.type == "array":
            schema["items"] = {"type": self.items or "string"}
        return schema


@dataclass(frozen=True)
class ToolSpec:
    """工具描述（与执行逻辑分离，便于前端展示与调试）。"""

    name: str
    description: str = ""
    parameters: tuple[ToolParameter, ...] = ()

    def to_openai_schema(self) -> dict[str, Any]:
        """转换为 OpenAI function calling 的工具定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {p.name: p.to_schema() for p in self.parameters},
                    "required": [p.name for p in self.parameters if p.required],
                },
            },
        }


class Tool(ABC):
    """工具基类。子类通过类属性声明描述，通过 ``invoke`` 实现行为。"""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    parameters: ClassVar[tuple[ToolParameter, ...]] = ()

    @abstractmethod
    def invoke(self, **kwargs: Any) -> str:
        """执行工具，返回给模型的字符串结果。"""

    async def invoke_async(self, **kwargs: Any) -> str:
        """异步执行工具（默认在后台线程运行同步 ``invoke``）。\n\n        需要真正异步的工具（如 MCP 调用）可覆盖此方法。\n        """
        return await asyncio.to_thread(self.invoke, **kwargs)

    def spec(self) -> ToolSpec:
        """返回工具描述（优先读取实例属性，支持 ``FunctionTool``/``McpTool`` 动态命名）。"""
        return ToolSpec(
            name=self.name, description=self.description, parameters=self.parameters
        )

    @classmethod
    def from_function(
        cls,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        parameters: Iterable[ToolParameter] = (),
    ) -> "FunctionTool":
        """把普通函数包装成工具。"""
        return FunctionTool(
            func,
            name=name,
            description=description,
            parameters=parameters,
        )


class FunctionTool(Tool):
    """把普通函数包装成 ``Tool``。"""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        parameters: Iterable[ToolParameter] = (),
    ) -> None:
        self._func = func
        self.name = name or func.__name__
        self.description = description or (func.__doc__ or "").strip()
        self.parameters = tuple(parameters)

    def invoke(self, **kwargs: Any) -> str:
        result = self._func(**kwargs)
        return "" if result is None else str(result)
