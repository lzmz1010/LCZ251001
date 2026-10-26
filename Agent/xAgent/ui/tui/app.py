"""Textual 终端界面。

本模块只做三件事：
1. 把 core 的事件流渲染成界面；
2. 把用户输入送回 core；
3. 管理界面自身的状态（输入框、状态栏、滚动）。

任何业务判断（何时调用工具、工具结果如何影响模型）都在 core 中完成。
"""

from __future__ import annotations

import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Footer, Header, TextArea

from core.agent import Agent
from core.events import (
    AgentEvent,
    ErrorEvent,
    MessageCompleteEvent,
    StatusEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from ui.base import Frontend
from ui.tui.widgets import ChatView, Composer, MessageBubble, StatusBar


class XAgentApp(App):
    """xAgent 的 Textual 应用。"""

    CSS_PATH = "styles.tcss"
    TITLE = "xAgent"

    BINDINGS = [
        Binding("ctrl+enter", "send", "发送", priority=True),
        Binding("ctrl+l", "clear_chat", "清空对话", priority=True),
        Binding("ctrl+q", "quit", "退出", priority=True),
    ]

    #: 流式渲染的最小间隔（秒），避免每个 token 都触发一次重排
    RENDER_INTERVAL = 0.08

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent
        self._busy = False
        self._bubble: MessageBubble | None = None
        self._pending = ""
        self._last_render = 0.0

    @property
    def agent(self) -> Agent:
        """当前使用的 Agent 实例。"""
        return self._agent

    def compose(self) -> ComposeResult:
        yield Header()
        yield ChatView(id="chat")
        yield Composer(id="composer")
        yield StatusBar("就绪", id="status")
        yield Footer()

    def on_mount(self) -> None:
        """界面就绪后聚焦输入框。"""
        self.sub_title = self._agent.model_name
        self.query_one("#composer", Composer).focus_input()
        self._set_status("就绪", "●")

    # ---------- 输入处理 ----------

    def action_send(self) -> None:
        """发送当前输入（Ctrl+Enter 或点击发送按钮）。"""
        if self._busy:
            self._set_status("上一轮还在生成中，请稍候…", "…")
            return
        composer = self.query_one("#composer", Composer)
        text = composer.text.strip()
        if not text:
            return
        composer.clear()
        self._busy = True
        self._set_status("思考中…", "…")
        self.run_worker(self._run_turn(text), group="agent", exit_on_error=False)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """响应发送按钮。"""
        if event.button.id == "send":
            self.action_send()

    async def action_clear_chat(self) -> None:
        """清空界面与对话历史。"""
        if self._busy:
            return
        await self.query_one("#chat", ChatView).clear()
        self._agent.session.clear()
        self._set_status("已清空对话", "●")

    # ---------- 事件渲染 ----------

    async def _run_turn(self, text: str) -> None:
        """执行一轮对话（运行在 worker 中，保持界面响应）。"""
        chat = self.query_one("#chat", ChatView)
        self._bubble = None
        self._pending = ""
        try:
            await chat.add_message("user", text)
            async for event in self._agent.stream_turn(text):
                await self._handle_event(event, chat)
        except Exception as exc:  # noqa: BLE001 - 界面不应因单次异常退出
            await chat.add_error(str(exc))
        finally:
            self._bubble = None
            self._pending = ""
            self._busy = False
            self._set_status("就绪", "●")

    async def _handle_event(self, event: AgentEvent, chat: ChatView) -> None:
        """把 core 事件翻译成界面变化。"""
        if isinstance(event, TextDeltaEvent):
            self._pending += event.text
            await self._flush(chat)
        elif isinstance(event, MessageCompleteEvent):
            await self._flush(chat, force=True)
        elif isinstance(event, ToolCallEvent):
            await chat.add_tool_call(event.name, event.arguments)
        elif isinstance(event, ToolResultEvent):
            await chat.add_tool_result(event.name, event.content, event.is_error)
        elif isinstance(event, StatusEvent):
            self._set_status(event.message, "⚙")
        elif isinstance(event, ErrorEvent):
            await chat.add_error(event.message)
        elif isinstance(event, TurnCompleteEvent):
            self._set_status("就绪", "●")

    async def _flush(self, chat: ChatView, force: bool = False) -> None:
        """按节流节奏刷新助手气泡。"""
        now = time.monotonic()
        if not force and (now - self._last_render) < self.RENDER_INTERVAL:
            return
        self._last_render = now
        text = self._pending
        self._pending = ""
        if not text:
            return
        if self._bubble is None:
            self._bubble = await chat.add_message("assistant", text)
        else:
            self._bubble.append_text(text)

    def _set_status(self, message: str, icon: str = "") -> None:
        """更新状态栏。"""
        self.query_one("#status", StatusBar).set_status(message, icon)


class TUIFrontend(Frontend):
    """Textual 前端适配器。"""

    name = "tui"

    def run(self, agent: Agent) -> None:
        """启动终端界面。"""
        XAgentApp(agent=agent).run()
