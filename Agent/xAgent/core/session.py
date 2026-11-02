"""会话上下文管理。

Session 保存完整聊天记录，每一轮都会把全部历史发送给大模型。
"""

from __future__ import annotations

from typing import Any, Iterable

from core.models import Message, ToolCall


class Session:
    """一次会话的上下文。"""

    def __init__(self, system_prompt: str = "") -> None:
        self._messages: list[Message] = []
        if system_prompt:
            self._messages.append(Message(role="system", content=system_prompt))

    @property
    def messages(self) -> list[Message]:
        """当前上下文中的全部消息。"""
        return list(self._messages)

    def set_system_prompt(self, content: str) -> Message:
        """替换系统提示词（用于刷新技能目录等动态内容）。"""
        message = Message(role="system", content=content)
        self._messages = [m for m in self._messages if m.role != "system"]
        self._messages.insert(0, message)
        return message

    def add_user(self, text: str) -> Message:
        """追加一条用户消息。"""
        message = Message(role="user", content=text)
        self._messages.append(message)
        return message

    def add_assistant(
        self, content: str, tool_calls: Iterable[ToolCall] = ()
    ) -> Message:
        """追加一条助手消息（可能同时携带工具调用）。"""
        message = Message(
            role="assistant", content=content, tool_calls=list(tool_calls)
        )
        self._messages.append(message)
        return message

    def add_tool_result(self, call_id: str, name: str, content: str) -> Message:
        """追加一条工具执行结果消息。"""
        message = Message(
            role="tool", content=content, tool_call_id=call_id, name=name
        )
        self._messages.append(message)
        return message

    def clear(self) -> None:
        """清空会话（保留系统提示词）。"""
        system_prompts = [m for m in self._messages if m.role == "system"]
        self._messages = list(system_prompts)

    def transcript(self) -> list[dict[str, Any]]:
        """导出可序列化的对话记录。"""
        return [message.to_dict() for message in self._messages]
