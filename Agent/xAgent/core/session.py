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

    def insert_context(self, message: Message) -> Message:
        """在系统提示词之后插入一条上下文消息（例如 AGENTS.md 注入）。"""
        index = 0
        while index < len(self._messages) and self._messages[index].role == "system":
            index += 1
        self._messages.insert(index, message)
        return message

    def restore_messages(self, messages: Iterable[Message]) -> None:
        """用外部消息列表整体替换会话历史（用于 /resume 恢复会话）。"""
        self._messages = list(messages)

    def replace_history_with_summary(
        self, summary: str, archive_id: str, compressed_at: str | None = None
    ) -> Message:
        """用压缩摘要替换历史上下文（保留系统提示词）。

        新的会话结构为：``[system] + [user(摘要 + 归档说明)]``。
        归档说明会提示模型：旧上下文已存到哪个编号的归档文件，
        需要时可通过 ``recallContext`` 工具检索。

        :param summary: LLM 生成的 Markdown 摘要。
        :param archive_id: 保存原始上下文的归档编号。
        :param compressed_at: 压缩时间（``YYYY-MM-DD HH:MM:SS``），缺省用当前时间。
        """
        if not compressed_at:
            from datetime import datetime

            compressed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        archive_note = (
            "【归档说明】此前上下文已于 %s 完成压缩，"
            "原始上下文保存在编号为 %s 的归档文件中。"
            "如需查找历史信息，请使用 recallContext 工具。"
        ) % (compressed_at, archive_id)
        content = f"【历史摘要】\n{summary}\n\n{archive_note}"

        system_prompts = [m for m in self._messages if m.role == "system"]
        message = Message(role="user", content=content)
        self._messages = system_prompts + [message]
        return message

    def transcript(self) -> list[dict[str, Any]]:
        """导出可序列化的对话记录。"""
        return [message.to_dict() for message in self._messages]
