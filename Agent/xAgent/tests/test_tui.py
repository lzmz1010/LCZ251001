"""TUI 前端的端到端冒烟测试（使用 Textual 的测试驱动，不依赖真实模型）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textual.widgets import TextArea  # noqa: E402

from core.agent import Agent  # noqa: E402
from core.llm.base import LLMClient, StreamChunk, ToolCallDelta  # noqa: E402
from core.session import Session  # noqa: E402
from core.tools.builtin import build_default_registry  # noqa: E402
from ui.tui.app import XAgentApp  # noqa: E402
from ui.tui.widgets import (  # noqa: E402
    MessageBubble,
    ToolCallBubble,
    ToolResultBubble,
)


class ScriptedLLM(LLMClient):
    """按脚本顺序返回预设分片的假客户端。"""

    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self.scripts = list(scripts)

    async def stream_chat(self, messages, tools=()):
        if not self.scripts:
            raise AssertionError("ScriptedLLM 没有更多脚本")
        for chunk in self.scripts.pop(0):
            yield chunk


def build_app(scripts) -> XAgentApp:
    agent = Agent(
        llm=ScriptedLLM(scripts),
        tools=build_default_registry(),
        session=Session(system_prompt="你是助手"),
    )
    return XAgentApp(agent=agent)


class TuiSmokeTests(unittest.IsolatedAsyncioTestCase):
    """验证 TUI 的输入、流式渲染与工具调用展示。"""

    async def _send(self, pilot, app: XAgentApp, text: str) -> None:
        app.query_one("#input", TextArea).text = text
        await pilot.press("ctrl+enter")

    async def _wait_for(self, pilot, predicate, timeout: float = 5.0) -> bool:
        elapsed = 0.0
        while elapsed < timeout:
            await pilot.pause(0.05)
            elapsed += 0.05
            if predicate():
                return True
        return False

    async def test_streaming_reply_is_rendered(self) -> None:
        app = build_app(
            [[StreamChunk(content="你好"), StreamChunk(content="，世界")]]
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "hi")

            ok = await self._wait_for(
                pilot,
                lambda: any(
                    "你好，世界" in bubble.text
                    for bubble in app.query(MessageBubble)
                ),
            )
            self.assertTrue(ok, "未在界面上看到流式回答")

            bubbles = list(app.query(MessageBubble))
            self.assertEqual(bubbles[0]._role, "user")
            self.assertEqual(bubbles[1]._role, "assistant")

    async def test_tool_call_is_rendered(self) -> None:
        app = build_app(
            [
                [
                    StreamChunk(
                        tool_calls=(
                            ToolCallDelta(
                                index=0,
                                id="call_1",
                                name="isLeapYear",
                                arguments='{"year": 2024}',
                            ),
                        )
                    )
                ],
                [StreamChunk(content="2024 是闰年")],
            ]
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "2024 是闰年吗")

            ok = await self._wait_for(
                pilot, lambda: len(app.query(ToolResultBubble)) == 1
            )
            self.assertTrue(ok, "未渲染工具调用气泡")
            self.assertEqual(len(app.query(ToolCallBubble)), 1)

            result = app.query(ToolResultBubble).first()
            self.assertIn("2024 是闰年", result._content)

    async def test_clear_chat(self) -> None:
        app = build_app([[StreamChunk(content="你好")]])
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "hi")
            await self._wait_for(
                pilot, lambda: len(app.query(MessageBubble)) >= 2
            )
            await pilot.press("ctrl+l")
            await pilot.pause()
            self.assertEqual(len(app.query(MessageBubble)), 0)
            # 会话历史被清空，但保留系统提示词
            self.assertEqual(
                [message.role for message in app.agent.session.messages], ["system"]
            )


if __name__ == "__main__":
    unittest.main()
