"""领域模型：消息与工具调用。

这些对象是 core 内部流转的“通用语言”，与具体的模型厂商 SDK 解耦。
转换成 OpenAI 协议格式由 ``to_dict`` 负责。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """模型请求调用的一次工具。"""

    id: str
    name: str
    arguments: str = "{}"

    def parsed_arguments(self) -> dict[str, Any]:
        """把原始 JSON 参数解析成字典，非法时返回空字典。"""
        if not self.arguments or not self.arguments.strip():
            return {}
        try:
            data = json.loads(self.arguments)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def to_dict(self) -> dict[str, Any]:
        """转换成 OpenAI function call 的协议格式。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class Message:
    """一条对话消息。"""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换成 OpenAI chat message 的协议格式。"""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [call.to_dict() for call in self.tool_calls]
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.name:
            payload["name"] = self.name
        return payload
