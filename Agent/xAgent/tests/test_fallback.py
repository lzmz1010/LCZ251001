"""主备双模型回退逻辑的单元测试。

运行：``python -m unittest discover -s tests -t .``（在 xAgent 目录下）
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent  # noqa: E402
from core.events import StatusEvent  # noqa: E402
from core.llm.base import LLMClient, StreamChunk  # noqa: E402
from core.llm.fallback import FallbackLLMClient  # noqa: E402
from core.session import Session  # noqa: E402
from core.tools.builtin import build_default_registry  # noqa: E402


class FakeLLM(LLMClient):
    """可控的假客户端：按预设行为返回流或抛异常。"""

    def __init__(
        self,
        name: str,
        chunks: list[StreamChunk],
        fail: bool = False,
        fail_count: int = 0,
    ) -> None:
        self._name = name
        self._chunks = chunks
        self._fail = fail
        #: 前 fail_count 次调用失败，之后恢复正常（用于测试自动恢复）
        self._fail_count = fail_count
        self.calls = 0

    @property
    def model_name(self) -> str:
        return self._name

    async def stream_chat(self, messages, tools=()):
        self.calls += 1
        if self._fail or self.calls <= self._fail_count:
            raise ConnectionError(f"{self._name} 不可用")
        for chunk in self._chunks:
            yield chunk


class FallbackLLMClientTests(unittest.IsolatedAsyncioTestCase):
    """验证主备切换行为。"""

    async def test_primary_success_no_switch(self) -> None:
        primary = FakeLLM("deepseek-v3", [StreamChunk(content="主模型回答")])
        fallback = FakeLLM("qwen3-8b", [StreamChunk(content="备用回答")])
        llm = FallbackLLMClient(primary, fallback)

        text = await llm.complete([])
        self.assertEqual(text, "主模型回答")
        self.assertEqual(llm.active_provider, "primary")
        self.assertEqual(llm.switch_count, 0)
        self.assertIsNone(llm.consume_notice())
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)

    async def test_primary_failure_switches_to_fallback(self) -> None:
        primary = FakeLLM("deepseek-v3", [], fail=True)
        fallback = FakeLLM("qwen3-8b", [StreamChunk(content="备用模型兜底")])
        llm = FallbackLLMClient(primary, fallback)

        text = await llm.complete([])
        self.assertEqual(text, "备用模型兜底")
        self.assertEqual(llm.active_provider, "fallback")
        self.assertEqual(llm.switch_count, 1)
        notice = llm.consume_notice()
        self.assertIsNotNone(notice)
        self.assertIn("deepseek-v3", notice)
        self.assertIn("qwen3-8b", notice)
        self.assertIsNone(llm.consume_notice())

    async def test_both_fail_raises(self) -> None:
        primary = FakeLLM("deepseek-v3", [], fail=True)
        fallback = FakeLLM("qwen3-8b", [], fail=True)
        llm = FallbackLLMClient(primary, fallback)

        with self.assertRaises(ConnectionError):
            await llm.complete([])

    async def test_primary_recovers_after_fallback(self) -> None:
        failing_primary = FakeLLM(
            "deepseek-v3", [StreamChunk(content="主模型恢复")], fail_count=1
        )
        fallback = FakeLLM("qwen3-8b", [StreamChunk(content="备用回答")])
        llm = FallbackLLMClient(failing_primary, fallback)

        text = await llm.complete([])  # 主模型第一次故障 → 回退
        self.assertEqual(text, "备用回答")
        self.assertEqual(llm.active_provider, "fallback")
        self.assertEqual(llm.switch_count, 1)

        text = await llm.complete([])  # 主模型已恢复 → 应优先使用主模型
        self.assertEqual(text, "主模型恢复")
        self.assertEqual(llm.active_provider, "primary")
        self.assertEqual(failing_primary.calls, 2)
        self.assertEqual(fallback.calls, 1)


class FallbackAgentTests(unittest.IsolatedAsyncioTestCase):
    """验证 Agent 集成：回退时输出 StatusEvent。"""

    async def test_fallback_emits_status_event(self) -> None:
        primary = FakeLLM("deepseek-v3", [], fail=True)
        fallback = FakeLLM("qwen3-8b", [StreamChunk(content="备用模型回答")])
        llm = FallbackLLMClient(primary, fallback)
        agent = Agent(
            llm=llm,
            tools=build_default_registry(),
            session=Session(system_prompt="你是助手"),
        )

        events = [event async for event in agent.stream_turn("你好")]
        status = next(e for e in events if isinstance(e, StatusEvent))
        self.assertIn("deepseek-v3", status.message)
        self.assertIn("qwen3-8b", status.message)


class FallbackConfigTests(unittest.TestCase):
    """验证配置装载能识别主备模型。"""

    def test_config_has_primary_and_backup(self) -> None:
        from core.config import load_config

        config = load_config(Path(__file__).resolve().parent.parent / "config.ini")
        self.assertEqual(config.llm.model, "deepseek-ai/DeepSeek-V3")
        self.assertIsNotNone(config.llm_backup)
        self.assertEqual(config.llm_backup.model, "qwen/qwen3-8b")
        self.assertIn("api.siliconflow.cn", config.llm.base_url)


if __name__ == "__main__":
    unittest.main()