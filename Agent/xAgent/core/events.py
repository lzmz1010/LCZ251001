"""核心层对外的事件定义。

core 只负责“发生了什么”，如何呈现完全交给前端：
- TUI / Web / Desktop / Mobile 都只需订阅这些事件并自行渲染。
- ``to_payload`` 提供 JSON 友好结构，便于 Web 端通过 SSE / WebSocket 推送。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, ClassVar


@dataclass
class AgentEvent:
    """所有事件的基类。"""

    type: ClassVar[str] = "event"

    def to_payload(self) -> dict[str, Any]:
        """转成可序列化的字典（供 Web / Mobile 端使用）。"""
        payload: dict[str, Any] = {"type": self.type}
        for item in fields(self):
            payload[item.name] = getattr(self, item.name)
        return payload


@dataclass
class UserMessageEvent(AgentEvent):
    """用户输入已被接收。"""

    type: ClassVar[str] = "user_message"
    text: str = ""


@dataclass
class TextDeltaEvent(AgentEvent):
    """模型输出的流式增量文本。"""

    type: ClassVar[str] = "text_delta"
    text: str = ""


@dataclass
class MessageCompleteEvent(AgentEvent):
    """本轮模型消息（含工具调用）生成完毕。"""

    type: ClassVar[str] = "message_complete"
    text: str = ""
    has_tool_calls: bool = False


@dataclass
class ToolCallEvent(AgentEvent):
    """模型请求调用某个工具。"""

    type: ClassVar[str] = "tool_call"
    call_id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class ToolResultEvent(AgentEvent):
    """工具执行结果。"""

    type: ClassVar[str] = "tool_result"
    call_id: str = ""
    name: str = ""
    content: str = ""
    is_error: bool = False


@dataclass
class ErrorEvent(AgentEvent):
    """执行过程中出现的错误。"""

    type: ClassVar[str] = "error"
    message: str = ""


@dataclass
class StatusEvent(AgentEvent):
    """状态提示（例如“正在调用工具”）。"""

    type: ClassVar[str] = "status"
    message: str = ""


@dataclass
class TurnCompleteEvent(AgentEvent):
    """一轮对话彻底结束，前端可以恢复输入。"""

    type: ClassVar[str] = "turn_complete"
    text: str = ""
