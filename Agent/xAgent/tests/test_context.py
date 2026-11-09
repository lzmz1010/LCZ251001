"""上下文管理：Token 估算、归档检索、压缩流程（不依赖真实模型服务）。

运行：``python -m unittest discover -s tests -t .``（在 xAgent 目录下）
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent  # noqa: E402
from core.config import ContextConfig  # noqa: E402
from core.context import ContextArchiver  # noqa: E402
from core.events import (  # noqa: E402
    ContextStatsEvent,
    ContextWarningEvent,
    ErrorEvent,
    TurnCompleteEvent,
)
from core.llm.base import LLMClient, StreamChunk  # noqa: E402
from core.models import ToolCall  # noqa: E402
from core.session import Session  # noqa: E402
from core.tokens import estimate_session_tokens, estimate_tokens  # noqa: E402
from core.tools.builtin import RecallContextTool, build_default_registry  # noqa: E402
from core.tools.registry import ToolRegistry  # noqa: E402


class FakeLLM(LLMClient):
    """按脚本返回分片的假客户端，可模拟 API 提供 prompt_tokens。"""

    def __init__(self, scripts, prompt_tokens=None):
        self.scripts = list(scripts)
        self.prompt_tokens = prompt_tokens
        self.calls = []

    @property
    def last_prompt_tokens(self):
        return self.prompt_tokens

    async def stream_chat(self, messages, tools=()):
        self.calls.append([m.to_dict() for m in messages])
        if not self.scripts:
            raise AssertionError("FakeLLM 没有更多脚本")
        for chunk in self.scripts.pop(0):
            yield chunk


class TokenEstimationTests(unittest.TestCase):
    """Token 估算逻辑。"""

    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_cjk_counts_one_per_char(self):
        self.assertEqual(estimate_tokens("你好世界"), 4)

    def test_ascii_roughly_four_per_token(self):
        self.assertEqual(estimate_tokens("abcdef"), 2)  # 6 个字符 → ceil(6/4)=2

    def test_session_estimation(self):
        session = Session(system_prompt="你是助手")
        session.add_user("你好")
        session.add_assistant("你好，有什么可以帮你？")
        self.assertGreater(estimate_session_tokens(session.messages), 0)


class ContextArchiverTests(unittest.TestCase):
    """归档保存与关键词检索。"""

    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.archiver = ContextArchiver(tmpdir.name)

    def _session(self) -> Session:
        session = Session(system_prompt="系统提示词")
        session.add_user("请帮我写一份国庆放假通知")
        session.add_assistant(
            "好的，我马上调用工具。",
            tool_calls=[ToolCall(id="call_1", name="getDate", arguments="{}")],
        )
        session.add_tool_result("call_1", "getDate", "2026-09-28")
        session.add_assistant("今天是 2026-09-28，我来写通知：全体员工国庆放假…")
        return session

    def test_save_creates_jsonl_and_unique_ids(self):
        session = self._session()
        first = self.archiver.save_session(session)
        second = self.archiver.save_session(session)
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^\d{8}-\d{6}$")
        self.assertTrue(self.archiver.archive_path(first).is_file())
        self.assertEqual(len(self.archiver.list_archive_ids()), 2)

    def test_save_preserves_order_and_content(self):
        archive_id = self.archiver.save_session(self._session())
        lines = self.archiver.archive_path(archive_id).read_text(
            encoding="utf-8"
        ).splitlines()
        records = [json.loads(line) for line in lines]
        roles = [r["role"] for r in records]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        self.assertIn("国庆放假通知", records[1]["content"])
        tool_rec = next(r for r in records if r["role"] == "tool")
        self.assertEqual(tool_rec["name"], "getDate")
        self.assertEqual(tool_rec["tool_call_id"], "call_1")

    def test_search_finds_keyword_in_archive(self):
        archive_id = self.archiver.save_session(self._session())
        result = self.archiver.search("国庆放假", archive_id=archive_id)
        self.assertIn(archive_id, result)
        self.assertIn("国庆放假通知", result)

    def test_search_without_id_scans_all(self):
        self.archiver.save_session(self._session())
        self.archiver.save_session(self._session())
        result = self.archiver.search("国庆")
        self.assertIn("国庆放假通知", result)
        self.assertIn("共 4 处", result)  # 每个归档命中 2 条（user + assistant）

    def test_search_unknown_id(self):
        result = self.archiver.search("国庆", archive_id="00000000-000000")
        self.assertIn("归档不存在", result)

    def test_search_no_match(self):
        session = Session(system_prompt="系统提示词")
        session.add_user("今天天气不错")
        self.archiver.save_session(session)
        result = self.archiver.search("股票行情")
        self.assertIn("未找到", result)

    def test_search_empty_text(self):
        self.assertEqual(
            self.archiver.search("   "), "recallContext 的参数 text 不能为空"
        )

    def test_search_handles_empty_archive_dir(self):
        archiver = ContextArchiver(tempfile.mkdtemp())
        result = archiver.search("随便")
        self.assertIn("没有任何历史上下文归档", result)


class RecallContextToolTests(unittest.TestCase):
    """recallContext 应作为一个普通 Function Calling 工具注册并可用。"""

    def test_registered_in_default_registry(self):
        registry = build_default_registry()
        self.assertIn("recallContext", registry.names)
        spec = registry.get("recallContext").spec()
        required = [p.name for p in spec.parameters if p.required]
        self.assertIn("text", required)
        self.assertNotIn("id", required)

    def test_execute_searches_archive(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        archiver = ContextArchiver(tmpdir.name)
        session = Session(system_prompt="系统")
        session.add_user("客户的服务器 IP 是 192.168.1.100")
        session.add_assistant("已记录：需要给服务器配置防火墙规则。")
        archive_id = archiver.save_session(session)

        registry = ToolRegistry([RecallContextTool(archive_dir=tmpdir.name)])
        result = registry.execute(
            "recallContext", json.dumps({"text": "192.168.1.100"})
        )
        self.assertFalse(result.is_error)
        self.assertIn("192.168.1.100", result.content)
        self.assertIn(archive_id, result.content)


class AgentCompressionTests(unittest.IsolatedAsyncioTestCase):
    """Agent 的 /compact 压缩流程与上下文监控。"""

    def _agent(self, llm, archive_dir) -> Agent:
        return Agent(
            llm=llm,
            tools=build_default_registry(archive_dir=archive_dir),
            session=Session(system_prompt="你是助手"),
            context_config=ContextConfig(archive_dir=archive_dir),
        )

    async def test_compress_saves_archive_and_replaces_history(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        llm = FakeLLM([[StreamChunk(content="# 工作摘要\n\n用户要求写一份放假通知。")]])
        agent = self._agent(llm, tmpdir.name)
        agent.session.add_user("请帮我写放假通知")
        agent.session.add_assistant("你好，我可以写通知。")

        result = await agent.compress()

        self.assertTrue(result.success)
        self.assertTrue(result.archive_id)
        # 原始上下文应被完整保存到归档
        archive_path = Path(tmpdir.name) / f"{result.archive_id}.jsonl"
        self.assertTrue(archive_path.is_file())
        records = [
            json.loads(line)
            for line in archive_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(records), 3)  # system + user + assistant
        self.assertEqual(records[1]["role"], "user")

        # 会话被替换为 system + user(摘要+归档说明)
        roles = [m.role for m in agent.session.messages]
        self.assertEqual(roles, ["system", "user"])
        content = agent.session.messages[-1].content
        self.assertIn("# 工作摘要", content)
        self.assertIn("放假通知", content)
        self.assertIn(result.archive_id, content)
        self.assertIn("recallContext", content)

    async def test_compress_failure_keeps_original_context(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        llm = FakeLLM([])  # 没有脚本 → 抛异常
        agent = self._agent(llm, tmpdir.name)
        agent.session.add_user("请保持我的原始上下文")

        result = await agent.compress()

        self.assertFalse(result.success)
        self.assertIn("保留原有上下文", result.message)
        self.assertEqual(
            [m.role for m in agent.session.messages], ["system", "user"]
        )
        self.assertEqual(
            agent.session.messages[-1].content, "请保持我的原始上下文"
        )

    async def test_compress_blocks_normal_turns(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        llm = FakeLLM([[StreamChunk(content="# 摘要")]])
        agent = self._agent(llm, tmpdir.name)
        agent._compressing = True
        events = [e async for e in agent.stream_turn("普通问题")]
        self.assertTrue(any(isinstance(e, ErrorEvent) for e in events))

    async def test_context_stats_prefers_api_tokens(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        llm = FakeLLM([[StreamChunk(content="好")]], prompt_tokens=50_000)
        agent = self._agent(llm, tmpdir.name)
        # 先完成一轮：Agent 会优先记录模型 API 返回的 prompt_tokens
        events = [e async for e in agent.stream_turn("hi")]
        stats = agent.context_stats()
        self.assertEqual(stats.used_tokens, 50_000)
        self.assertEqual(stats.window_tokens, 128_000)
        self.assertTrue(stats.window_is_default)

    def test_window_not_default_when_configured(self):
        agent = Agent(
            llm=FakeLLM([]),
            tools=build_default_registry(),
            session=Session(),
            context_config=ContextConfig(
                context_window=131_072, window_is_default=False
            ),
        )
        stats = agent.context_stats()
        self.assertEqual(stats.window_tokens, 131_072)
        self.assertFalse(stats.window_is_default)

    async def test_blocked_when_ratio_exceeds_threshold(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        # 会话很小但实测 token 被记录为 900（模拟 API 返回高占用）
        agent = Agent(
            llm=FakeLLM([]),
            tools=build_default_registry(),
            session=Session(system_prompt="你是助手"),
            context_config=ContextConfig(
                context_window=1000, window_is_default=False
            ),
        )
        agent._measured_tokens = 900
        self.assertTrue(agent.context_stats().blocked)
        self.assertFalse(agent.can_accept_input())
        events = [e async for e in agent.stream_turn("被拦截的消息")]
        self.assertTrue(any(isinstance(e, ContextWarningEvent) for e in events))
        # 被拦截的消息不应写入会话
        self.assertEqual([m.role for m in agent.session.messages], ["system"])

    def test_not_blocked_below_threshold(self):
        llm = FakeLLM([[StreamChunk(content="好")]], prompt_tokens=80_000)
        agent = Agent(
            llm=llm,
            tools=build_default_registry(),
            session=Session(system_prompt="你是助手"),
        )
        self.assertFalse(agent.context_stats().blocked)
        self.assertTrue(agent.can_accept_input())

    async def test_turn_emits_context_stats_event(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        llm = FakeLLM([[StreamChunk(content="你好")]], prompt_tokens=200)
        agent = self._agent(llm, tmpdir.name)
        events = [e async for e in agent.stream_turn("hi")]
        stats_events = [e for e in events if isinstance(e, ContextStatsEvent)]
        self.assertEqual(len(stats_events), 1)
        self.assertEqual(stats_events[0].used_tokens, 200)
        self.assertTrue(any(isinstance(e, TurnCompleteEvent) for e in events))

    async def test_turn_emits_warning_when_consumed_over_threshold(self):
        llm = FakeLLM([[StreamChunk(content="你好")]], prompt_tokens=90_000)
        agent = Agent(
            llm=llm,
            tools=build_default_registry(),
            session=Session(system_prompt="你是助手"),
        )
        events = [e async for e in agent.stream_turn("hi")]
        self.assertTrue(any(isinstance(e, ContextWarningEvent) for e in events))

    async def test_compress_resets_measured_tokens(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        llm = FakeLLM([[StreamChunk(content="# 摘要\n\n已完成任务。")]])
        agent = self._agent(llm, tmpdir.name)
        agent.session.add_user("长对话之后上下文快满了")
        # 模拟实测值很大 → 触发拦截
        agent._measured_tokens = 90_000
        self.assertFalse(agent.can_accept_input())

        result = await agent.compress()
        self.assertTrue(result.success)
        # 压缩后实测值被清空，不再误拦截
        self.assertTrue(agent.can_accept_input())

    async def test_compress_uses_compression_prompt(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        llm = FakeLLM([[StreamChunk(content="# 摘要")]])
        agent = self._agent(llm, tmpdir.name)
        await agent.compress()
        self.assertEqual(len(llm.calls), 1)
        assert llm.calls[0][0]["role"] == "system"
        assert "上下文管理助手" in llm.calls[0][0]["content"]
        assert llm.calls[0][1]["role"] == "user"


if __name__ == "__main__":
    unittest.main()