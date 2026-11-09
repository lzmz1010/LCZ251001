"""core 层的单元测试（不依赖真实模型服务）。

运行：``python -m unittest discover -s tests -t .``（在 xAgent 目录下）
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent  # noqa: E402
from core.events import (  # noqa: E402
    ErrorEvent,
    MessageCompleteEvent,
    StatusEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
    UserMessageEvent,
)
from core.llm.base import LLMClient, StreamChunk, ToolCallDelta  # noqa: E402
from core.session import Session  # noqa: E402
from core.tools.builtin import (  # noqa: E402
    FetchWebTool,
    RunCliTool,
    SearchWebTool,
    build_default_registry,
)
from core.tools.builtin.cli_tool import MAX_OUTPUT_CHARS  # noqa: E402
from core.tools.registry import ToolRegistry  # noqa: E402


class FakeLLMClient(LLMClient):
    """按脚本顺序返回预设分片的假客户端。"""

    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self.scripts = list(scripts)
        self.calls: list[list[dict]] = []

    async def stream_chat(self, messages, tools=()):
        self.calls.append([m.to_dict() for m in messages])
        if not self.scripts:
            raise AssertionError("FakeLLMClient 没有更多脚本")
        for chunk in self.scripts.pop(0):
            yield chunk


def tool_chunk(name: str, arguments: str, call_id: str = "call_1") -> StreamChunk:
    """构造一个包含工具调用的流式分片。"""
    return StreamChunk(
        tool_calls=(ToolCallDelta(index=0, id=call_id, name=name, arguments=arguments),)
    )


class AgentCoreTests(unittest.IsolatedAsyncioTestCase):
    """验证 Agent 核心循环与工具调用流程。"""

    def _make_agent(self, scripts, max_tool_rounds: int = 8) -> tuple[Agent, FakeLLMClient]:
        llm = FakeLLMClient(scripts)
        agent = Agent(
            llm=llm,
            tools=build_default_registry(),
            session=Session(system_prompt="你是助手"),
            max_tool_rounds=max_tool_rounds,
        )
        return agent, llm

    async def test_plain_answer_stream(self) -> None:
        """普通回答应输出增量文本并结束本轮。"""
        agent, llm = self._make_agent(
            [[StreamChunk(content="你好"), StreamChunk(content="，世界")]]
        )
        events = [event async for event in agent.stream_turn("hi")]

        self.assertIsInstance(events[0], UserMessageEvent)
        self.assertEqual(
            "".join(e.text for e in events if isinstance(e, TextDeltaEvent)),
            "你好，世界",
        )
        self.assertTrue(any(isinstance(e, TurnCompleteEvent) for e in events))
        self.assertEqual(llm.calls[0][0]["role"], "system")

    async def test_tool_call_round_trip(self) -> None:
        """模型请求工具时应执行工具并把结果回传给模型。"""
        agent, llm = self._make_agent(
            [
                [tool_chunk("isLeapYear", '{"year": 2024}')],
                [StreamChunk(content="2024 是闰年")],
            ]
        )
        events = [event async for event in agent.stream_turn("2024 是闰年吗")]

        call_events = [e for e in events if isinstance(e, ToolCallEvent)]
        result_events = [e for e in events if isinstance(e, ToolResultEvent)]
        self.assertEqual(len(call_events), 1)
        self.assertEqual(call_events[0].name, "isLeapYear")
        self.assertEqual(result_events[0].content, "2024 是闰年")
        self.assertFalse(result_events[0].is_error)

        # 第二次请求应带上 tool 消息
        second_call = llm.calls[1]
        tool_messages = [m for m in second_call if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0]["tool_call_id"], "call_1")

        # 会话历史：system + user + assistant(tool_calls) + tool + assistant(最终回答)
        roles = [message.role for message in agent.session.messages]
        self.assertEqual(
            roles, ["system", "user", "assistant", "tool", "assistant"]
        )

    async def test_unknown_tool_returns_error(self) -> None:
        """未知工具应返回错误结果而不是抛出异常。"""
        agent, _ = self._make_agent(
            [
                [tool_chunk("noSuchTool", "{}")],
                [StreamChunk(content="抱歉")],
            ]
        )
        events = [event async for event in agent.stream_turn("随便调用")]
        result = next(e for e in events if isinstance(e, ToolResultEvent))
        self.assertTrue(result.is_error)
        self.assertIn("未知工具", result.content)

    async def test_invalid_tool_arguments(self) -> None:
        """非法 JSON 参数应被捕获并反馈给模型。"""
        agent, _ = self._make_agent(
            [
                [tool_chunk("isLeapYear", "not-json")],
                [StreamChunk(content="参数有问题")],
            ]
        )
        events = [event async for event in agent.stream_turn("闰年")]
        result = next(e for e in events if isinstance(e, ToolResultEvent))
        self.assertTrue(result.is_error)
        self.assertIn("JSON", result.content)

    async def test_max_tool_rounds_guard(self) -> None:
        """工具调用轮数超限时输出错误事件。"""
        agent, _ = self._make_agent(
            [[tool_chunk("getDate", "{}")] for _ in range(5)], max_tool_rounds=2
        )
        events = [event async for event in agent.stream_turn("循环调用")]
        self.assertTrue(any(isinstance(e, ErrorEvent) for e in events))

    async def test_empty_response_is_retried_then_answered(self) -> None:
        """模型偶发返回空响应时应自动重试，而不是静默结束。"""
        agent, llm = self._make_agent(
            [
                [],  # 第一次请求空响应
                [StreamChunk(content="好的，我重试成功了")],
            ]
        )
        events = [event async for event in agent.stream_turn("hi")]

        text = "".join(e.text for e in events if isinstance(e, TextDeltaEvent))
        self.assertEqual(text, "好的，我重试成功了")
        self.assertTrue(any(isinstance(e, StatusEvent) for e in events))
        self.assertFalse(any(isinstance(e, ErrorEvent) for e in events))
        # 空响应不被写入会话历史（只发出两次请求，不含空消息）
        self.assertEqual(len(llm.calls), 2)

    async def test_empty_response_exhausted_reports_error(self) -> None:
        """连续空响应时应在界面上给出明确错误，而不是沉默。"""
        agent, _ = self._make_agent([[], [], []])
        events = [event async for event in agent.stream_turn("hi")]

        errors = [e for e in events if isinstance(e, ErrorEvent)]
        self.assertEqual(len(errors), 1)
        self.assertIn("未返回任何内容", errors[0].message)
        self.assertTrue(any(isinstance(e, StatusEvent) for e in events))
        # 会话中没有写入空的 assistant 消息
        roles = [m.role for m in agent.session.messages]
        self.assertEqual(roles, ["system", "user"])


class ToolRegistryTests(unittest.TestCase):
    """工具注册表行为测试。"""

    def test_builtin_registry_contains_tools(self) -> None:
        registry = build_default_registry()
        self.assertIn("getDate", registry.names)
        self.assertIn("searchWeb", registry.names)
        self.assertIn("fetchWeb", registry.names)
        self.assertIn("RunCli", registry.names)
        self.assertIn("isLeapYear", registry.names)

    def test_execute_missing_parameter(self) -> None:
        registry = build_default_registry()
        result = registry.execute("isLeapYear", "{}")
        self.assertTrue(result.is_error)
        self.assertIn("year", result.content)

    def test_openai_schema_shape(self) -> None:
        registry = build_default_registry()
        schema = registry.to_openai_schema()
        names = {item["function"]["name"] for item in schema}
        self.assertEqual(
            names,
            {
                "getDate",
                "searchWeb",
                "fetchWeb",
                "RunCli",
                "isLeapYear",
                "getCwd",
                "listDir",
                "getFileType",
                "readFile",
                "createFile",
                "editFile",
                "mkdir",
                "rmDir",
                "rmFile",
                "recallContext",
            },
        )
        for item in schema:
            self.assertEqual(item["type"], "function")
            self.assertIn("parameters", item["function"])

        run_cli = next(
            item for item in schema if item["function"]["name"] == "RunCli"
        )
        args_schema = run_cli["function"]["parameters"]["properties"]["args"]
        self.assertEqual(args_schema["type"], "array")
        self.assertEqual(args_schema["items"], {"type": "string"})

    def test_get_date_tool_returns_text(self) -> None:
        registry = build_default_registry()
        result = registry.execute("getDate", "")
        self.assertFalse(result.is_error)
        self.assertTrue(result.content)


class _FakeHTTPResponse:
    """模拟 urlopen 返回的响应对象。"""

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args) -> bool:
        return False


class SearchWebToolTests(unittest.TestCase):
    """联网搜索工具测试（使用假的 HTTP 响应，不访问真实接口）。"""

    def test_requires_api_key(self) -> None:
        registry = ToolRegistry([SearchWebTool(api_key="")])
        result = registry.execute("searchWeb", '{"query": "北京天气"}')
        self.assertTrue(result.is_error)
        self.assertIn("未配置", result.content)
        self.assertIn("baidu_qianfan_api_key", result.content)

    def test_api_error_is_returned_to_llm(self) -> None:
        payload = {
            "requestId": "test-request",
            "code": 216003,
            "message": "Authentication error",
        }
        registry = ToolRegistry([SearchWebTool(api_key="test-key")])
        with patch(
            "core.tools.builtin.search_tool.urlopen",
            lambda request, timeout=None: _FakeHTTPResponse(payload),
        ):
            result = registry.execute("searchWeb", '{"query": "北京天气"}')

        self.assertTrue(result.is_error)
        self.assertIn("216003", result.content)
        self.assertIn("Authentication error", result.content)
        self.assertIn("test-request", result.content)

    def test_network_error_is_returned_to_llm(self) -> None:
        def fake_urlopen(request, timeout=None):
            raise URLError("connection refused")

        registry = ToolRegistry([SearchWebTool(api_key="test-key")])
        with patch("core.tools.builtin.search_tool.urlopen", fake_urlopen):
            result = registry.execute("searchWeb", '{"query": "北京天气"}')

        self.assertTrue(result.is_error)
        self.assertIn("无法连接百度千帆搜索接口", result.content)
        self.assertIn("connection refused", result.content)

    def test_formats_summary_and_references(self) -> None:
        payload = {
            "references": [
                {
                    "id": 1,
                    "title": "北京天气预报",
                    "url": "https://example.com/weather",
                    "content": "北京今天晴，气温 18-27℃。",
                },
                {
                    "id": 2,
                    "title": "北京天气实况",
                    "url": "https://example.com/live",
                    "snippet": "北京当前空气质量优。",
                },
            ],
            "request_id": "test-request",
        }
        captured: dict = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["headers"] = {
                key.lower(): value for key, value in request.header_items()
            }
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeHTTPResponse(payload)

        registry = ToolRegistry([
            SearchWebTool(api_key="test-key", edition="turbo", timeout=12)
        ])
        with patch("core.tools.builtin.search_tool.urlopen", fake_urlopen):
            result = registry.execute("searchWeb", '{"query": "北京天气"}')

        self.assertFalse(result.is_error)
        self.assertIn("搜索摘要：", result.content)
        self.assertIn("北京今天晴", result.content)
        self.assertIn("参考来源：", result.content)
        self.assertIn("北京天气预报", result.content)
        self.assertIn("https://example.com/weather", result.content)

        self.assertEqual(
            captured["url"],
            "https://qianfan.baidubce.com/v2/ai_search/web_search",
        )
        self.assertEqual(captured["headers"]["authorization"], "Bearer test-key")
        self.assertEqual(captured["payload"]["messages"][0]["content"], "北京天气")
        self.assertEqual(captured["payload"]["search_source"], "baidu_search_v2")
        self.assertEqual(captured["payload"]["edition"], "turbo")
        self.assertEqual(captured["timeout"], 12)

    def test_no_result_message(self) -> None:
        tool = SearchWebTool(api_key="test-key")
        self.assertIn("未搜索到", tool._format({"references": []}))


class FetchWebToolTests(unittest.TestCase):
    """网页正文抓取工具测试（mock curl，不访问真实网络）。"""

    URL = "https://example.com/article"

    @staticmethod
    def _html() -> bytes:
        paragraph = (
            "这是文章正文的一段内容，用于测试正文提取效果。它包含足够多的文字，"
            "以便算法能够识别出主要内容区域，而不是导航栏或页脚。"
        )
        return f"""<html><head><title>测试文章</title></head><body>
<header><nav><a href="/home">首页导航</a> | <a href="/news">新闻导航</a></nav></header>
<main><article>
<h1>测试文章标题</h1>
<p>{paragraph}</p>
<h2>第一节</h2>
<p>{paragraph} 这里有<a href="https://example.com/doc">一个链接</a>。</p>
<ul><li>列表项一</li><li>列表项二</li></ul>
<table><thead><tr><th>列A</th><th>列B</th></tr></thead>
<tbody><tr><td>值1</td><td>值2</td></tr></tbody></table>
<h2>第二节</h2>
<p>{paragraph}</p><p>{paragraph}</p><p>{paragraph}</p>
</article></main>
<footer>版权所有 页脚广告</footer>
</body></html>""".encode("utf-8")

    def _completed(self, stdout: bytes = b"", returncode: int = 0, stderr: bytes = b""):
        return subprocess.CompletedProcess(
            args=["curl"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    def _execute(self, arguments: dict):
        registry = ToolRegistry([FetchWebTool(curl_path="curl")])
        return registry.execute("fetchWeb", json.dumps(arguments))

    def test_extracts_markdown_and_removes_boilerplate(self) -> None:
        with patch(
            "core.tools.builtin.fetch_tool.subprocess.run",
            return_value=self._completed(stdout=self._html()),
        ) as fake_run:
            result = self._execute({"url": self.URL})

        self.assertFalse(result.is_error)
        self.assertIn(f"来源 URL: {self.URL}", result.content)
        self.assertIn("# 测试文章标题", result.content)
        self.assertIn("## 第一节", result.content)
        self.assertIn("- 列表项一", result.content)
        self.assertIn("| 列A |", result.content)
        self.assertIn("[一个链接](https://example.com/doc)", result.content)
        self.assertNotIn("首页导航", result.content)
        self.assertNotIn("页脚广告", result.content)

        args = fake_run.call_args.args[0]
        self.assertIsInstance(args, list)
        self.assertEqual(args[args.index("--url") + 1], self.URL)
        self.assertNotEqual(fake_run.call_args.kwargs.get("shell"), True)

    def test_rejects_invalid_url(self) -> None:
        with patch("core.tools.builtin.fetch_tool.subprocess.run") as fake_run:
            result = self._execute({"url": "file:///C:/secret.txt"})

        self.assertTrue(result.is_error)
        self.assertIn("URL 无效", result.content)
        fake_run.assert_not_called()

    def test_curl_failure_is_returned_to_llm(self) -> None:
        with patch(
            "core.tools.builtin.fetch_tool.subprocess.run",
            return_value=self._completed(
                returncode=22, stderr=b"curl: (22) The requested URL returned error: 404"
            ),
        ):
            result = self._execute({"url": self.URL})

        self.assertTrue(result.is_error)
        self.assertIn("退出码 22", result.content)
        self.assertIn("404", result.content)

    def test_timeout_is_returned_to_llm(self) -> None:
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="curl", timeout=30)

        with patch("core.tools.builtin.fetch_tool.subprocess.run", fake_run):
            result = self._execute({"url": self.URL})

        self.assertTrue(result.is_error)
        self.assertIn("超时", result.content)

    def test_missing_curl_is_returned_to_llm(self) -> None:
        with patch("core.tools.builtin.fetch_tool.shutil.which", return_value=None):
            registry = ToolRegistry([FetchWebTool()])
        result = registry.execute("fetchWeb", json.dumps({"url": self.URL}))

        self.assertTrue(result.is_error)
        self.assertIn("未找到本地 curl", result.content)

    def test_html_parse_failure_is_returned_to_llm(self) -> None:
        with patch(
            "core.tools.builtin.fetch_tool.subprocess.run",
            return_value=self._completed(stdout=b"<html></html>"),
        ), patch(
            "core.tools.builtin.fetch_tool.trafilatura.load_html",
            return_value=None,
        ):
            result = self._execute({"url": self.URL})

        self.assertTrue(result.is_error)
        self.assertIn("HTML 解析失败", result.content)

    def test_extraction_failure_is_returned_to_llm(self) -> None:
        with patch(
            "core.tools.builtin.fetch_tool.subprocess.run",
            return_value=self._completed(stdout=self._html()),
        ), patch(
            "core.tools.builtin.fetch_tool.trafilatura.extract",
            return_value=None,
        ):
            result = self._execute({"url": self.URL})

        self.assertTrue(result.is_error)
        self.assertIn("未能从网页中提取正文", result.content)


class RunCliToolTests(unittest.TestCase):
    """本地 CLI 工具测试（mock subprocess，不执行真实命令）。"""

    def _completed(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["cmd"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def _execute(self, arguments: dict):
        registry = ToolRegistry([RunCliTool()])
        return registry.execute("RunCli", json.dumps(arguments))

    def test_returns_stdout_stderr_and_exit_code(self) -> None:
        with patch(
            "core.tools.builtin.cli_tool.subprocess.run",
            return_value=self._completed(
                stdout=b"hello\n", stderr=b"", returncode=0
            ),
        ) as fake_run:
            result = self._execute(
                {"command": "python", "args": ["--version"]}
            )

        self.assertFalse(result.is_error)
        self.assertIn("退出码: 0", result.content)
        self.assertIn("标准输出:", result.content)
        self.assertIn("hello", result.content)
        self.assertIn("标准错误:（无输出）", result.content)

        argv = fake_run.call_args.args[0]
        self.assertEqual(argv, ["python", "--version"])
        self.assertNotEqual(fake_run.call_args.kwargs.get("shell"), True)

    def test_non_zero_exit_is_returned_to_llm(self) -> None:
        with patch(
            "core.tools.builtin.cli_tool.subprocess.run",
            return_value=self._completed(
                stdout=b"partial output", stderr=b"boom", returncode=2
            ),
        ):
            result = self._execute({"command": "demo"})

        self.assertFalse(result.is_error)
        self.assertIn("退出码: 2", result.content)
        self.assertIn("partial output", result.content)
        self.assertIn("boom", result.content)

    def test_rejects_empty_command(self) -> None:
        result = self._execute({"command": "   "})
        self.assertTrue(result.is_error)
        self.assertIn("command 必须是非空", result.content)

    def test_rejects_non_string_args(self) -> None:
        with patch("core.tools.builtin.cli_tool.subprocess.run") as fake_run:
            result = self._execute({"command": "demo", "args": [1, 2]})

        self.assertTrue(result.is_error)
        self.assertIn("必须是字符串", result.content)
        fake_run.assert_not_called()

    def test_missing_command_is_returned_to_llm(self) -> None:
        def fake_run(*args, **kwargs):
            raise FileNotFoundError("demo")

        with patch("core.tools.builtin.cli_tool.subprocess.run", fake_run):
            result = self._execute({"command": "not-a-real-command"})

        self.assertTrue(result.is_error)
        self.assertIn("未找到命令", result.content)
        self.assertIn("not-a-real-command", result.content)

    def test_timeout_is_returned_to_llm(self) -> None:
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd="demo", timeout=30, output=b"partial", stderr=b"still running"
            )

        with patch("core.tools.builtin.cli_tool.subprocess.run", fake_run):
            result = self._execute({"command": "demo"})

        self.assertTrue(result.is_error)
        self.assertIn("命令执行超时", result.content)
        self.assertIn("partial", result.content)
        self.assertIn("still running", result.content)

    def test_long_output_is_truncated(self) -> None:
        with patch(
            "core.tools.builtin.cli_tool.subprocess.run",
            return_value=self._completed(
                stdout=b"a" * (MAX_OUTPUT_CHARS + 100)
            ),
        ):
            result = self._execute({"command": "demo"})

        self.assertFalse(result.is_error)
        self.assertIn("已截断", result.content)
        self.assertIn(f"原始长度 {MAX_OUTPUT_CHARS + 100} 字符", result.content)
        self.assertLess(len(result.content), MAX_OUTPUT_CHARS + 500)


class ConfigTests(unittest.TestCase):
    """配置装载测试。"""

    def test_load_config(self) -> None:
        from core.config import load_config

        config = load_config(Path(__file__).resolve().parent.parent / "config.ini")
        self.assertTrue(config.llm.model)
        self.assertTrue(config.search.api_key)
        self.assertTrue(config.search.edition)
        self.assertGreaterEqual(config.agent.max_tool_rounds, 1)

    def test_with_overrides(self) -> None:
        from core.config import AppConfig

        config = AppConfig().with_overrides(
            llm_model="demo-model", search_edition="turbo"
        )
        self.assertEqual(config.llm.model, "demo-model")
        self.assertEqual(config.search.edition, "turbo")


if __name__ == "__main__":
    unittest.main()
