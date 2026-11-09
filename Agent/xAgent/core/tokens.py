"""Token 使用量估算。

模型 API 能在响应中返回实际的 ``prompt_tokens`` 时优先使用该值；
无法获得时（本地服务不支持、或做预判时），用这里的启发式估算。

估算规则（简单、可解释，适合教学）：
- CJK（中文/日文/韩文）字符：一个字符约相当于 1 个 token；
- 其它字符（英文、数字、标点、空白）：每 4 个字符约相当于 1 个 token。
"""

from __future__ import annotations

import json
from typing import Iterable

from core.models import Message


def _is_cjk(code: int) -> bool:
    """判断一个码点是否属于 CJK 全宽字符区（中文为主）。"""
    return (
        0x4E00 <= code <= 0x9FFF  # CJK 统一表意文字
        or 0x3000 <= code <= 0x303F  # CJK 标点（、。「」等）
        or 0xFF01 <= code <= 0xFF60  # 全角符号
        or 0xFFE0 <= code <= 0xFFE6  # 全角 ￥｜
    )


def estimate_tokens(text: str) -> int:
    """估算一段文本对应的 token 数量。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ord(ch)))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def estimate_message_tokens(message: Message) -> int:
    """估算单条消息（含角色、内容、工具调用）占用的 token 数。"""
    payload = json.dumps(message.to_dict(), ensure_ascii=False)
    return estimate_tokens(payload)


def estimate_session_tokens(messages: Iterable[Message]) -> int:
    """估算整个会话上下文占用的 token 数。"""
    return sum(estimate_message_tokens(message) for message in messages)


__all__ = [
    "estimate_message_tokens",
    "estimate_session_tokens",
    "estimate_tokens",
]