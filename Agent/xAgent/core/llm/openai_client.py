"""OpenAI 兼容协议适配器。

支持所有暴露 ``/v1/chat/completions`` 且兼容 function calling 的服务：
LM Studio、Ollama、vLLM、OneAPI、DeepSeek、OpenAI 官方等。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Sequence

from openai import AsyncOpenAI

from core.config import LLMConfig
from core.errors import LLMError
from core.llm.base import LLMClient, StreamChunk, ToolCallDelta
from core.models import Message
from core.tools.base import ToolSpec


class OpenAIChatClient(LLMClient):
    """基于 OpenAI 兼容接口的流式客户端。"""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        if not config.model:
            raise LLMError("未配置模型名称（llm.model）")
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "not-needed",
            timeout=config.timeout,
        )

    @property
    def config(self) -> LLMConfig:
        """返回当前配置。"""
        return self._config

    @property
    def model_name(self) -> str:
        """当前使用的模型名称。"""
        return self._config.model

    async def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[StreamChunk]:
        """请求模型并逐段产出输出。"""
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [message.to_dict() for message in messages],
            "stream": True,
        }
        if self._config.temperature is not None:
            payload["temperature"] = self._config.temperature
        if self._config.max_tokens is not None:
            payload["max_tokens"] = self._config.max_tokens
        if tools:
            payload["tools"] = [spec.to_openai_schema() for spec in tools]
        payload.update(self._config.extra)

        try:
            stream = await self._client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001 - 统一转换为业务异常
            raise LLMError(f"调用模型失败: {exc}") from exc

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None) or ""
            tool_deltas: list[ToolCallDelta] = []
            for tool_call in getattr(delta, "tool_calls", None) or ():
                function = getattr(tool_call, "function", None)
                tool_deltas.append(
                    ToolCallDelta(
                        index=(
                            tool_call.index if tool_call.index is not None else 0
                        ),
                        id=tool_call.id,
                        name=getattr(function, "name", None),
                        arguments=getattr(function, "arguments", None),
                    )
                )
            if content or tool_deltas:
                yield StreamChunk(content=content, tool_calls=tuple(tool_deltas))
