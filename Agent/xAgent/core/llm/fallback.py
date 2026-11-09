"""主备双模型客户端：主模型请求失败时自动回退到备用模型。

实现 ``LLMClient`` 接口，对 core/agent.py 完全透明：
``stream_chat`` 优先请求主模型，任何异常（网络/超时/上下文超限/鉴权等）
都会自动切换到备用模型继续完成本轮请求。

主模型恢复后，下一次请求仍会优先尝试主模型（自动恢复）。
回退发生时通过 ``consume_notice()`` 向外暴露一条可读提示，
Agent 会把它转成 ``StatusEvent`` 展示给用户。
"""

from __future__ import annotations

from typing import AsyncIterator, Sequence

from core.llm.base import LLMClient, StreamChunk
from core.models import Message
from core.tools.base import ToolSpec


class FallbackLLMClient(LLMClient):
    """按「主 → 备」顺序请求，主失败时自动切换到备用模型。"""

    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        if primary is fallback:
            raise ValueError("主模型与备用模型不能是同一个实例")
        self._primary = primary
        self._fallback = fallback
        self._active: LLMClient = primary
        self._switch_count = 0
        self._pending_notice: str | None = None

    @property
    def primary(self) -> LLMClient:
        """主模型客户端。"""
        return self._primary

    @property
    def fallback(self) -> LLMClient:
        """备用模型客户端。"""
        return self._fallback

    @property
    def active_provider(self) -> str:
        """当前生效的提供方：``primary`` 或 ``fallback``。"""
        return "fallback" if self._active is self._fallback else "primary"

    @property
    def switch_count(self) -> int:
        """累计回退次数。"""
        return self._switch_count

    @property
    def model_name(self) -> str:
        """当前生效的模型名称（界面展示用）。"""
        return self._active.model_name

    @property
    def last_prompt_tokens(self) -> int | None:
        """最近一次实际生效请求的 prompt token 数。"""
        return self._active.last_prompt_tokens

    def consume_notice(self) -> str | None:
        """取出最近一次回退发生时的提示文案，取后即清空。"""
        notice = self._pending_notice
        self._pending_notice = None
        return notice

    async def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[StreamChunk]:
        """优先请求主模型，失败则回退到备用模型。"""
        # 每次请求都从主模型重新开始，主模型恢复后自动切回
        self._active = self._primary
        self._pending_notice = None
        try:
            async for chunk in self._primary.stream_chat(messages, tools):
                yield chunk
            return
        except Exception as exc:  # noqa: BLE001 - 主模型任何异常都应触发回退
            self._switch_to_fallback(exc)

        async for chunk in self._fallback.stream_chat(messages, tools):
            yield chunk

    def _switch_to_fallback(self, primary_error: Exception) -> None:
        self._active = self._fallback
        self._switch_count += 1
        notice = (
            f"主模型 {self._primary.model_name} 调用失败，"
            f"已自动回退到备用模型 {self._fallback.model_name}（第 {self._switch_count} 次）。"
            f"失败原因: {primary_error}"
        )
        self._pending_notice = notice


__all__ = ["FallbackLLMClient"]