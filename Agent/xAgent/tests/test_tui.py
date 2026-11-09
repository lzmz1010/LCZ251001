"""TUI 前端的端到端冒烟测试（使用 Textual 的测试驱动，不依赖真实模型）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textual.widgets import TextArea  # noqa: E402

from core.agent import Agent  # noqa: E402
from core.config import ContextConfig  # noqa: E402
from core.llm.base import LLMClient, StreamChunk, ToolCallDelta  # noqa: E402
from core.session import Session  # noqa: E402
from core.tools.builtin import build_default_registry  # noqa: E402
from ui.tui.app import XAgentApp  # noqa: E402
from ui.tui.widgets import (  # noqa: E402
    ContextBar,
    McpSidebar,
    MessageBubble,
    SessionListPanel,
    SlashPalette,
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

    async def test_context_bar_is_visible(self) -> None:
        """上下文占用信息栏应显示占用大小/窗口大小/百分比与「默认」提示。"""
        app = build_app([[StreamChunk(content="你好")]])
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "hi")
            await self._wait_for(
                pilot, lambda: len(app.query(MessageBubble)) >= 2
            )
            bar = app.query_one("#context", ContextBar)
            text = str(bar.render())
            self.assertIn("上下文", text)
            self.assertIn("128k", text)  # 默认上下文窗口 128k
            self.assertIn("「默认」", text)  # 未显式配置窗口 → 显示默认提示
            self.assertIn("%", text)

    async def test_slash_palette_appears_after_slash(self) -> None:
        """输入 / 应弹出命令补全面板并列出候选命令。"""
        app = build_app([[StreamChunk(content="你好")]])
        async with app.run_test() as pilot:
            await pilot.pause()
            textarea = app.query_one("#input", TextArea)
            textarea.text = "/"
            await pilot.pause()
            palette = app.query_one("#palette", SlashPalette)
            self.assertTrue(palette.display, "补全面板应显示")
            self.assertGreater(len(palette.list.children), 0)
            # 继续输入过滤
            textarea.text = "/sa"
            await pilot.pause()
            names = [
                item.data.get("command")
                for item in palette.list.children
                if getattr(item, "data", None)
            ]
            self.assertEqual(names, ["save"])

    async def test_help_command_renders_command_list(self) -> None:
        app = build_app([[StreamChunk(content="你好")]])
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "/help")
            ok = await self._wait_for(
                pilot,
                lambda: any(
                    isinstance(b, MessageBubble)
                    and b._role == "system"
                    and "可用斜杠命令" in b.text
                    for b in app.query(MessageBubble)
                ),
            )
            self.assertTrue(ok, "未展示命令帮助")

    async def test_save_command_persists_session(self) -> None:
        app = build_app([[StreamChunk(content="你好")]])
        agent = app.agent
        agent.session.add_user("请记录一条好消息")
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "/save")
            ok = await self._wait_for(
                pilot,
                lambda: any(
                    isinstance(b, MessageBubble)
                    and b._role == "system"
                    and "已保存会话" in b.text
                    for b in app.query(MessageBubble)
                ),
            )
            self.assertTrue(ok, "会话未保存")
            self.assertGreater(len(app.session_store.list()), 0)

    async def test_new_command_saves_and_resets(self) -> None:
        app = build_app([[StreamChunk(content="你好")]])
        app.agent.session.add_user("旧的会话内容")
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "/new")
            ok = await self._wait_for(
                pilot,
                lambda: any(
                    isinstance(b, MessageBubble)
                    and b._role == "system"
                    and "已新建会话" in b.text
                    for b in app.query(MessageBubble)
                ),
            )
            self.assertTrue(ok, "未提示新建会话")
            roles = [m.role for m in app.agent.session.messages]
            self.assertEqual(roles, ["system"], "新会话应仅保留系统提示词")

    async def test_mcp_sidebar_is_rendered(self) -> None:
        app = build_app([[StreamChunk(content="你好")]])
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#mcp", McpSidebar)
            self.assertIn("MCP", str(sidebar.render()))

    async def test_resume_panel_opens_with_saved_sessions(self) -> None:
        app = build_app([[StreamChunk(content="你好")]])
        meta = app.session_store.save(app.agent.session)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "/resume")
            ok = await self._wait_for(
                pilot, lambda: app.query_one("#session-list").display
            )
            self.assertTrue(ok, "会话列表未弹出")
            panel = app.query_one("#session-list", SessionListPanel)
            ids = [
                item.data.get("session_id")
                for item in panel.list.children
                if getattr(item, "data", None)
            ]
            self.assertIn(meta.id, ids)

    async def test_compact_command_replaces_history(self) -> None:
        """输入 /compact 应触发压缩，归档并替换历史。"""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        llm = ScriptedLLM([[StreamChunk(content="# 工作摘要\n\n已完成主要任务。")]])
        agent = Agent(
            llm=llm,
            tools=build_default_registry(archive_dir=tmpdir.name),
            session=Session(system_prompt="你是助手"),
            context_config=ContextConfig(archive_dir=tmpdir.name),
        )
        agent.session.add_user("请写一份放假通知")
        agent.session.add_assistant("好的，我来写。")
        app = XAgentApp(agent=agent)

        async with app.run_test() as pilot:
            await pilot.pause()
            await self._send(pilot, app, "/compact")
            ok = await self._wait_for(
                pilot,
                lambda: any(
                    isinstance(b, MessageBubble)
                    and b._role == "system"
                    and "上下文压缩完成" in b.text
                    for b in app.query(MessageBubble)
                ),
            )
            self.assertTrue(ok, "界面上未出现压缩完成提示")

            # 会话被替换为 system + user(摘要 + 归档说明)
            roles = [m.role for m in app.agent.session.messages]
            self.assertEqual(roles, ["system", "user"])
            content = app.agent.session.messages[-1].content
            self.assertIn("工作摘要", content)
            self.assertIn("recallContext", content)


if __name__ == "__main__":
    unittest.main()
