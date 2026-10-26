"""大模型客户端：抽象接口与各厂商适配器。"""

from core.llm.base import LLMClient, StreamChunk, ToolCallDelta
from core.llm.openai_client import OpenAIChatClient

__all__ = ["LLMClient", "OpenAIChatClient", "StreamChunk", "ToolCallDelta"]
