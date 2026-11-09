"""会话存储、AGENTS.md 注入、配置自动生成与参数化配置的单元测试。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import (
    AgentsConfig,
    CliConfig,
    ConfigCreatedError,
    FetchConfig,
    SearchConfig,
    load_config,
)
from core.errors import ConfigError
from core.models import ToolCall
from core.session import Session
from core.sessions import SessionStore
from core.tools.builtin import (
    FetchWebTool,
    RecallContextTool,
    RunCliTool,
    SearchWebTool,
    build_default_registry,
)
from core.tools.registry import ToolRegistry


class SessionStoreTests(unittest.TestCase):
    """会话保存 / 列出 / 恢复。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.store = SessionStore(self.tmpdir.name)

    def _session(self, title: str) -> Session:
        session = Session(system_prompt="系统提示词")
        session.add_user(title)
        session.add_assistant("好的，我来处理。")
        return session

    def test_save_and_list(self) -> None:
        meta = self.store.save(self._session("请写一份通知"))
        self.assertRegex(meta.id, r"^\d{8}-\d{6}(\-\d+)?$")
        self.assertIn("通知", meta.title)
        self.assertGreaterEqual(meta.count, 2)
        entries = self.store.list()
        self.assertEqual([e.id for e in entries], [meta.id])

    def test_load_round_trip_preserves_roles(self) -> None:
        session = Session(system_prompt="系统")
        session.add_user("你好")
        session.add_assistant(
            "我来查一下", tool_calls=[ToolCall(id="c1", name="getDate", arguments="{}")]
        )
        session.add_tool_result("c1", "getDate", "2026-11-05")
        meta = self.store.save(session)

        messages = self.store.load(meta.id)
        roles = [m.role for m in messages]
        self.assertEqual(roles, ["system", "user", "assistant", "tool"])
        self.assertEqual(messages[-1].content, "2026-11-05")
        tools = messages[2].tool_calls
        self.assertEqual(tools[0].name, "getDate")
        self.assertEqual(tools[0].arguments, "{}")

    def test_load_unknown_id_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.store.load("00000000-000000")


class AgentsMdInjectionTests(unittest.TestCase):
    """AGENTS.md 一次注入、全程复用。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmpdir.name)
        self.addCleanup(os.chdir, self._cwd)

    def _agent(self, md_content: str = "# 规则\n- 用中文回答"):
        from core.agent import Agent

        Path(self.tmpdir.name, "AGENTS.md").write_text(md_content, encoding="utf-8")
        return Agent(
            llm=None,  # type: ignore[arg-type] - 测试注入逻辑不请求模型
            tools=ToolRegistry(),
            session=Session(system_prompt="系统"),
            agents_config=AgentsConfig(inject=True, md_file="AGENTS.md"),
        )

    def test_inject_once_and_idempotent(self) -> None:
        agent = self._agent()
        first = agent.inject_agents_md()
        second = agent.inject_agents_md()  # 重复调用不应重复注入
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        injected = [m for m in agent.session.messages if m.role == "user"]
        self.assertEqual(len(injected), 1)
        self.assertIn("【项目约定 AGENTS.md】", injected[0].content)
        self.assertIn("- 用中文回答", injected[0].content)
        # 注入位置在系统提示词之后
        roles = [m.role for m in agent.session.messages]
        self.assertEqual(roles, ["system", "user"])

    def test_reset_session_reinjects(self) -> None:
        agent = self._agent()
        agent.inject_agents_md()
        agent.session.add_user("真实问题")
        agent.session.add_assistant("回答")
        agent.reset_session()
        user_messages = [m for m in agent.session.messages if m.role == "user"]
        # 只保留重新注入的 AGENTS.md 一条 user 消息
        self.assertEqual(len(user_messages), 1)
        self.assertIn("【项目约定 AGENTS.md】", user_messages[0].content)

    def test_disabled_or_missing_file_skips(self) -> None:
        from core.agent import Agent

        agent = Agent(
            llm=None,  # type: ignore[arg-type]
            tools=ToolRegistry(),
            session=Session(system_prompt="系统"),
            agents_config=AgentsConfig(inject=False),
        )
        self.assertIsNone(agent.inject_agents_md())
        agent2 = Agent(
            llm=None,  # type: ignore[arg-type]
            tools=ToolRegistry(),
            session=Session(system_prompt="系统"),
            agents_config=AgentsConfig(inject=True, md_file="NO_SUCH_FILE.md"),
        )
        self.assertIsNone(agent2.inject_agents_md())


class ConfigAutoCreateTests(unittest.TestCase):
    """config.ini 缺失时自动生成示例配置并抛 ConfigCreatedError。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmpdir.name)
        self.addCleanup(os.chdir, self._cwd)

    def test_missing_config_creates_template(self) -> None:
        with self.assertRaises(ConfigCreatedError) as ctx:
            load_config(None)
        generated = Path(self.tmpdir.name) / "config.ini"
        self.assertTrue(generated.is_file())
        text = generated.read_text(encoding="utf-8")
        self.assertIn("[llm]", text)
        self.assertIn("[llm_backup]", text)
        self.assertIn("[agents]", text)
        self.assertIn("[sessions]", text)
        self.assertIn("[ui]", text)
        self.assertIn("AGENTS.md", text)
        self.assertIn("config.ini", str(ctx.exception))
        self.assertEqual(str(ctx.exception.path), str(generated))

    def test_existing_config_still_loads(self) -> None:
        (Path(self.tmpdir.name) / "config.ini").write_text(
            "[llm]\nmodel = demo\n[context]\n", encoding="utf-8"
        )
        config = load_config(None)
        self.assertEqual(config.llm.model, "demo")


class ConfigParamPlumbingTests(unittest.TestCase):
    """硬编码参数改为从 config.ini 获取并传导到工具实例。"""

    def test_cli_and_fetch_config_flow(self) -> None:
        registry = build_default_registry(
            cli_config=CliConfig(timeout=5.0, max_output_chars=200),
            fetch_config=FetchConfig(
                timeout=9.0, max_html_bytes=12345, user_agent="UA-test"
            ),
        )
        cli = registry.get("RunCli")
        fetch = registry.get("fetchWeb")
        self.assertEqual(cli._timeout, 5.0)
        self.assertEqual(cli._max_output_chars, 200)
        self.assertEqual(fetch._timeout, 9.0)
        self.assertEqual(fetch._max_html_bytes, 12345)
        self.assertEqual(fetch._user_agent, "UA-test")

    def test_search_summary_max_chars_flow(self) -> None:
        tool = SearchWebTool.from_config(
            SearchConfig(api_key="k", summary_max_chars=100)
        )
        content = tool._format(
            {"references": [{"content": "x" * 300, "title": "t", "url": "u"}]}
        )
        self.assertIn("...", content)
        self.assertLess(len(content), 300)

    def test_recall_context_reads_context_params(self) -> None:
        from core.config import ContextConfig

        registry = build_default_registry(
            recall_limit=2, snippet_max_chars=20
        )
        self.assertEqual(registry.get("recallContext")._archiver._recall_limit, 2)
        self.assertEqual(
            registry.get("recallContext")._archiver._snippet_max_chars, 20
        )


if __name__ == "__main__":
    unittest.main()