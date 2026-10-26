"""Agent 主循环。

这是 core 的核心业务逻辑：接收用户输入 → 请求模型 → 如有工具调用则执行并回传 →
再次请求模型，直到得到最终回答。整个过程通过事件流输出，界面只负责渲染。
"""

from __future__ import annotations

from typing import AsyncIterator, Sequence

from core.events import (
    AgentEvent,
    ErrorEvent,
    MessageCompleteEvent,
    StatusEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
    UserMessageEvent,
)
from core.llm.base import LLMClient
from core.models import ToolCall
from core.session import Session
from core.tools.base import ToolSpec
from core.tools.registry import ToolRegistry


class Agent:
    """带有工具调用能力的对话代理。"""

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        session: Session | None = None,
        max_tool_rounds: int = 8,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._session = session or Session()
        self._max_tool_rounds = max_tool_rounds

    @property
    def session(self) -> Session:
        """当前会话上下文。"""
        return self._session

    @property
    def model_name(self) -> str:
        """当前模型名称（供界面展示）。"""
        return self._llm.model_name

    @property
    def tools(self) -> ToolRegistry:
        """当前工具注册表。"""
        return self._tools

    def tool_specs(self) -> Sequence[ToolSpec]:
        """可提供给模型的工具描述。"""
        return self._tools.specs()

    async def stream_turn(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """执行一轮对话，以事件流的形式输出全部中间过程。"""
        user_message = self._session.add_user(user_input)
        yield UserMessageEvent(text=user_message.content)

        final_text = ""
        rounds = 0
        while True:
            if rounds >= self._max_tool_rounds:
                yield ErrorEvent(
                    message=f"已达到最大工具调用轮数 ({self._max_tool_rounds})，本轮提前结束"
                )
                break
            rounds += 1

            content_parts: list[str] = []
            tool_calls: dict[int, ToolCall] = {}

            async for chunk in self._llm.stream_chat(
                messages=self._session.messages,
                tools=self._tools.specs(),
            ):
                if chunk.content:
                    content_parts.append(chunk.content)
                    yield TextDeltaEvent(text=chunk.content)
                for delta in chunk.tool_calls:
                    call = tool_calls.get(delta.index)
                    if call is None:
                        call = ToolCall(
                            id=delta.id or "", name=delta.name or "", arguments=""
                        )
                        tool_calls[delta.index] = call
                    if delta.id:
                        call.id = delta.id
                    if delta.name:
                        call.name = delta.name
                    if delta.arguments:
                        call.arguments += delta.arguments

            content = "".join(content_parts)
            ordered_calls = list(tool_calls.values())
            self._session.add_assistant(content, ordered_calls)
            yield MessageCompleteEvent(
                text=content, has_tool_calls=bool(ordered_calls)
            )

            if not ordered_calls:
                final_text = content
                break

            for call in ordered_calls:
                yield ToolCallEvent(
                    call_id=call.id, name=call.name, arguments=call.arguments
                )
            for call in ordered_calls:
                yield StatusEvent(message=f"正在执行工具 {call.name}")
                result = self._tools.execute(call.name, call.arguments)
                self._session.add_tool_result(call.id, call.name, result.content)
                yield ToolResultEvent(
                    call_id=call.id,
                    name=call.name,
                    content=result.content,
                    is_error=result.is_error,
                )

        yield TurnCompleteEvent(text=final_text)

    async def ask(self, user_input: str) -> str:
        """执行一轮对话并返回最终文本（非流式便捷接口）。"""
        final_text = ""
        async for event in self.stream_turn(user_input):
            if isinstance(event, TurnCompleteEvent):
                final_text = event.text
        return final_text


__all__ = ["Agent"]
