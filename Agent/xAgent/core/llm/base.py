"""大模型客户端抽象。

core 只依赖 ``LLMClient`` 接口，具体厂商实现放在本目录下作为适配器，
新增厂商（如 Anthropic、通义、Ollama）时新增一个适配器即可，core 无需改动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Sequence

from core.models import Message
from core.tools.base import ToolSpec


@dataclass(frozen=True)
class ToolCallDelta:
    """流式返回中的工具调用增量。"""

    index: int = 0
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


@dataclass(frozen=True)
class StreamChunk:
    """模型流式输出的一个片段。"""

    content: str = ""
    tool_calls: tuple[ToolCallDelta, ...] = ()

    @property
    def has_tool_calls(self) -> bool:
        """该片段是否包含工具调用信息。"""
        return bool(self.tool_calls)


class LLMClient(ABC):
    """大模型客户端接口。"""

    @property
    def model_name(self) -> str:
        """模型名称，供界面展示使用。"""
        return ""

    @abstractmethod
    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[StreamChunk]:
        """以流式方式请求模型，逐段返回 ``StreamChunk``。"""
