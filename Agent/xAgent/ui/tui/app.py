"""Textual 终端界面。

本模块只做三件事：
1. 把 core 的事件流渲染成界面；
2. 把用户输入送回 core；
3. 管理界面自身的状态（输入框、状态栏、滚动、斜杠命令、MCP 边栏）。

任何业务判断（何时调用工具、工具结果如何影响模型）都在 core 中完成。

斜杠命令：输入 ``/`` 自动弹出补全面板（↑↓ 选择、Enter 执行、Esc 关闭、
继续输入可过滤）。内置命令见 ``COMMAND_SPECS``。
"""

from __future__ import annotations

import asyncio
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, TextArea

from core.agent import Agent
from core.bootstrap import attach_mcp_async
from core.events import (
    AgentEvent,
    ContextStatsEvent,
    ContextWarningEvent,
    ErrorEvent,
    MessageCompleteEvent,
    StatusEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from core.sessions import SessionMeta, SessionStore
from ui.base import Frontend
from ui.tui.widgets import (
    ChatView,
    Composer,
    ContextBar,
    McpSidebar,
    MessageBubble,
    SessionListPanel,
    SlashPalette,
    StatusBar,
)


class XAgentApp(App):
    """xAgent 的 Textual 应用。"""

    CSS_PATH = "styles.tcss"
    TITLE = "xAgent"

    BINDINGS = [
        Binding("ctrl+enter", "send", "发送", priority=True),
        Binding("ctrl+l", "clear_chat", "清空对话", priority=True),
        Binding("ctrl+q", "quit", "退出", priority=True),
        Binding("tab", "view_skills", "查看技能", priority=True),
        Binding("escape", "dismiss_overlay", "关闭面板", priority=True),
    ]

    #: 上下文信息栏自动刷新间隔（秒）
    CONTEXT_REFRESH_INTERVAL = 5.0

    #: 流式渲染的最小间隔（秒），避免每个 token 都触发一次重排
    RENDER_INTERVAL = 0.08

    COMMAND_SPECS: list[tuple[str, str]] = [
        ("new", "新建会话（自动保存当前会话历史）"),
        ("resume", "恢复历史会话（↑↓ 选择，Enter 恢复，Esc 取消）"),
        ("save", "保存当前会话"),
        ("compact", "压缩上下文（归档并生成摘要）"),
        ("clear", "清空对话历史"),
        ("help", "查看全部命令"),
        ("skills", "查看本地技能"),
        ("model", "查看当前模型"),
        ("context", "查看上下文占用"),
        ("mcp", "查看 MCP 服务器状态"),
        ("quit", "退出"),
    ]

    _ASYNC_COMMANDS = {
        "compact",
        "new",
        "save",
        "clear",
        "skills",
        "model",
        "context",
        "mcp",
    }

    def __init__(self, agent: Agent, config=None) -> None:
        super().__init__()
        self._agent = agent
        self._config = config
        if config is not None:
            self.CONTEXT_REFRESH_INTERVAL = config.ui.context_refresh_interval
            self.RENDER_INTERVAL = config.ui.render_interval
        self._store = SessionStore(
            (config.sessions.dir if config is not None else None)
        )
        self._mcp = None
        self._busy = False
        self._bubble: MessageBubble | None = None
        self._pending = ""
        self._last_render = 0.0

    @property
    def agent(self) -> Agent:
        """当前使用的 Agent 实例。"""
        return self._agent

    @property
    def session_store(self) -> SessionStore:
        """会话保存/恢复仓库。"""
        return self._store

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            yield ChatView(id="chat")
            yield McpSidebar()
        yield SlashPalette(self.COMMAND_SPECS)
        yield ContextBar("上下文 --", id="context")
        yield SessionListPanel()
        yield Composer(id="composer")
        yield StatusBar("就绪", id="status")
        yield Footer()

    def on_mount(self) -> None:
        """界面就绪后聚焦输入框、显示初态上下文、异步加载 MCP。"""
        self.sub_title = self._agent.model_name
        self.query_one("#composer", Composer).focus_input()
        self._set_status("就绪", "●")
        self._render_context()
        self.set_interval(self.CONTEXT_REFRESH_INTERVAL, self._render_context)
        self.run_worker(self._load_mcp(), group="mcp", exit_on_error=False)

    # ---------- 输入与命令 ----------

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

        if text.startswith("/"):
            self._dispatch_command(text)
            return

        if not self._agent.can_accept_input():
            stats = self._agent.context_stats()
            self._set_status(
                f"上下文已占用 {stats.ratio * 100:.0f}%，已暂停接收新输入，请先输入 /compact 压缩", "!"
            )
            self._render_context()
            return

        self._busy = True
        self._set_status("思考中…", "…")
        self.run_worker(self._run_turn(text), group="agent", exit_on_error=False)

    def _dispatch_command(self, line: str) -> None:
        """分发斜杠命令（/name [arg]）。"""
        name = line[1:].partition(" ")[0].strip().lower()
        if name == "resume":
            self._open_resume_panel()
        elif name == "quit":
            self.exit()
        elif name == "help":
            self.run_worker(
                self._cmd_help(), group="cmd", exit_on_error=False
            )
        elif name in self._ASYNC_COMMANDS:
            self._busy = True
            self.run_worker(
                self._handle_command(name), group="cmd", exit_on_error=False
            )
        else:
            self._set_status(f"未知命令 /{name}，输入 /help 查看可用命令", "!")
            self.run_worker(
                self._chat_task(
                    lambda: self.query_one("#chat", ChatView).add_error(
                        f"未知命令: /{name}\n输入 /help 查看全部命令"
                    )
                ),
                group="agent",
                exit_on_error=False,
            )

    async def _handle_command(self, name: str) -> None:
        """执行常见的异步斜杠命令。"""
        chat = self.query_one("#chat", ChatView)
        try:
            if name == "compact":
                await self._run_compact()
            elif name == "new":
                await self._cmd_new()
            elif name == "save":
                meta = await asyncio.to_thread(self._store.save, self._agent.session)
                await chat.add_message(
                    "system",
                    f"已保存会话 {meta.id}\n时间: {meta.saved_at}\n标题: {meta.title}",
                )
                self._set_status("会话已保存", "●")
            elif name == "clear":
                await chat.clear()
                self._agent.session.clear()
                self._set_status("已清空对话", "●")
            elif name == "skills":
                await self._cmd_skills()
            elif name == "model":
                await chat.add_message(
                    "system",
                    f"当前模型: {self._agent.model_name}\n"
                    f"提供方: {self._provider_label()}",
                )
            elif name == "context":
                stats = self._agent.context_stats()
                await chat.add_message(
                    "system",
                    f"上下文占用: {stats.used_tokens} / {stats.window_tokens} tokens\n"
                    f"比率: {stats.ratio * 100:.1f}%\n"
                    + ("已超过阈值，建议 /compact" if stats.blocked else "占用正常"),
                )
            elif name == "mcp":
                self._refresh_mcp_sidebar()
                servers = (
                    self._mcp.connected_servers() if self._mcp is not None else []
                )
                await chat.add_message(
                    "system",
                    f"MCP 服务器状态（右侧边栏）: 已连接 {len(servers)} 个。"
                    if servers
                    else "MCP 服务器状态（右侧边栏）: 尚未连接任何服务器。",
                )
        except Exception as exc:  # noqa: BLE001
            await chat.add_error(f"命令执行失败: {exc}")
        finally:
            self._busy = False
            self._set_status("就绪", "●")

    async def _cmd_help(self) -> None:
        """展示全部斜杠命令（/help）。"""
        chat = self.query_one("#chat", ChatView)
        lines = ["可用斜杠命令：", ""]
        for name, hint in self.COMMAND_SPECS:
            lines.append(f"  /{name:<12} {hint}")
        lines.append("")
        lines.append("输入 / 后会自动弹出补全面板，↑↓ 选择、Enter 执行、Esc 取消。")
        await chat.add_message("system", "\n".join(lines))
        self._busy = False
        self._set_status("就绪", "●")

    def _provider_label(self) -> str:
        llm = getattr(self._agent, "_llm", None)
        if llm is not None and getattr(llm, "active_provider", "primary") == "fallback":
            return "主模型失败，已回退到备用模型"
        return "主模型"

    async def _cmd_skills(self) -> None:
        """把技能清单渲染为工具结果气泡。"""
        chat = self.query_one("#chat", ChatView)
        tool = self._agent.tools.get("listSkills")
        if tool is None:
            await chat.add_error("未注册技能查看工具 listSkills")
            return
        await chat.add_tool_result("查看技能", str(tool.invoke()), is_error=False)

    async def _run_compact(self) -> None:
        """执行上下文压缩（/compact 命令）。"""
        chat = self.query_one("#chat", ChatView)
        try:
            await chat.add_message("system", "开始压缩上下文…")
            result = await self._agent.compress()
            self._render_context()
            if result.success:
                await chat.add_message(
                    "system",
                    f"上下文压缩完成\n归档编号: {result.archive_id}\n{result.message}",
                )
            else:
                await chat.add_error(
                    f"上下文压缩失败，已保留原有上下文：{result.message}"
                )
        except Exception as exc:  # noqa: BLE001
            await chat.add_error(f"上下文压缩出错: {exc}")

    async def _cmd_new(self) -> None:
        """新建会话：自动保存当前会话历史，然后重置。"""
        chat = self.query_one("#chat", ChatView)
        session = self._agent.session
        saved = ""
        has_content = any(m.role == "user" for m in session.messages)
        if has_content:
            meta = await asyncio.to_thread(self._store.save, session)
            saved = f"原会话已保存为: {meta.id}\n"
        self._agent.reset_session()
        await chat.clear()
        injected = self._agent.inject_agents_md()
        await chat.add_message(
            "system",
            f"已新建会话\n{saved}"
            + ("AGENTS.md 项目约定已注入\n" if injected is not None else ""),
        )
        self._render_context()

    async def _cmd_resume(self, session_id: str) -> None:
        """恢复指定会话并重渲染聊天区。"""
        chat = self.query_one("#chat", ChatView)
        try:
            messages = await asyncio.to_thread(self._store.load, session_id)
            self._agent.session.restore_messages(messages)
            await chat.clear()
            for message in self._agent.session.messages:
                if message.role in ("user", "assistant") and message.content:
                    await chat.add_message(message.role, message.content)
                elif message.role == "tool":
                    await chat.add_tool_result(
                        message.name or "工具", message.content
                    )
            await chat.add_message(
                "system",
                f"已恢复会话 {session_id}（{len(messages)} 条消息）",
            )
            self._render_context()
            self._set_status(f"已恢复会话 {session_id}", "●")
        except Exception as exc:  # noqa: BLE001
            await chat.add_error(f"恢复会话失败: {exc}")
        finally:
            self._busy = False

    # ---------- 斜杠补全面板 ----------

    def on_text_area_changed(self, event) -> None:
        """输入框内容变化时维护补全面板。"""
        text_area = getattr(event, "text_area", None)
        if text_area is None or text_area.id != "input":
            return
        text = text_area.text
        if text.lstrip().startswith("/") and not self._resume_visible():
            self._show_palette(text)
        else:
            self._hide_palette(focus_input=False)

    def on_key(self, event) -> None:
        """补全面板打开时，把字符/退格转发到输入框（实现“边键入边过滤”）。"""
        if not self._palette_visible():
            return
        key = event.key
        textarea = self.query_one("#input", TextArea)
        if key == "backspace":
            current = textarea.text
            if current:
                textarea.text = current[:-1]
            self._update_palette()
            event.stop()
        elif key is not None and key.isprintable() and len(key) == 1:
            textarea.text += key
            self._update_palette()
            event.stop()

    def _show_palette(self, text: str) -> None:
        palette = self.query_one("#palette", SlashPalette)
        filter_text = text.lstrip()
        if filter_text.startswith("/"):
            filter_text = filter_text[1:]
        matches = palette.refresh_items(filter_text)
        palette.display = bool(matches)
        if matches:
            self._set_palette_selection(0)
            palette.list.focus()

    def _update_palette(self) -> None:
        text = self.query_one("#input", TextArea).text
        if text.lstrip().startswith("/"):
            self._show_palette(text)
        else:
            self._hide_palette(focus_input=False)

    def _set_palette_selection(self, index: int) -> None:
        palette = self.query_one("#palette", SlashPalette)
        try:
            if palette.list.children:
                palette.list.index = index
        except Exception:  # noqa: BLE001 - 不同 Textual 版本 API 差异
            pass

    def _palette_visible(self) -> bool:
        palette = self.query_one("#palette", SlashPalette)
        return palette.display

    def _resume_visible(self) -> bool:
        panel = self.query_one("#session-list", SessionListPanel)
        return panel.display

    def _hide_palette(self, focus_input: bool = False) -> None:
        palette = self.query_one("#palette", SlashPalette)
        palette.display = False
        if focus_input:
            self.query_one("#composer", Composer).focus_input()

    # ---------- 历史会话面板 ----------

    def _open_resume_panel(self) -> None:
        """打开历史会话列表（/resume）。"""
        metas = self._store.list()
        panel = self.query_one("#session-list", SessionListPanel)
        if not metas:
            self.run_worker(
                self._chat_task(
                    lambda: self.query_one("#chat", ChatView).add_message(
                        "system", "暂无已保存的会话，使用 /save 或 /new 保存会话。"
                    )
                ),
                group="agent",
                exit_on_error=False,
            )
            self._set_status("暂无历史会话", "●")
            return
        panel.refresh_items(metas)
        panel.display = True
        panel.list.focus()

    def action_dismiss_overlay(self) -> None:
        """Esc：关闭补全面板或会话列表。"""
        if self._resume_visible():
            panel = self.query_one("#session-list", SessionListPanel)
            panel.display = False
            self._set_status("已取消恢复会话", "●")
            self.query_one("#composer", Composer).focus_input()
        elif self._palette_visible():
            self._hide_palette(focus_input=True)

    # ---------- 事件渲染 ----------

    async def _chat_task(self, factory):
        """运行一个只与界面交互的协程任务。"""
        async def run():
            await factory()
        return run()

    async def on_list_view_selected(self, event) -> None:
        """补全面板 / 会话列表选中项。"""
        item = event.item
        data = getattr(item, "data", None) or {}
        if "command" in data:
            name = data["command"]
            self._hide_palette(focus_input=True)
            self._dispatch_command(f"/{name}")
        elif "session_id" in data:
            session_id = data["session_id"]
            self.action_dismiss_overlay()
            self._busy = True
            self.run_worker(
                self._cmd_resume(session_id), group="cmd", exit_on_error=False
            )

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
            self._render_context()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """响应发送按钮。"""
        if event.button.id == "send":
            self.action_send()

    async def action_clear_chat(self) -> None:
        """清空界面与对话历史（Ctrl+L）。"""
        if self._busy:
            return
        await self.query_one("#chat", ChatView).clear()
        self._agent.session.clear()
        self._set_status("已清空对话", "●")

    async def action_view_skills(self) -> None:
        """查看当前已装载的技能（Tab 键）。"""
        chat = self.query_one("#chat", ChatView)
        tool = self._agent.tools.get("listSkills")
        if tool is None:
            await chat.add_error("未注册技能查看工具 listSkills")
            return
        await chat.add_tool_result("查看技能", str(tool.invoke()), is_error=False)

    def _render_context(self) -> None:
        """刷新上下文占用信息栏（界面尚未挂载完成时静默跳过）。"""
        try:
            bar = self.query_one("#context", ContextBar)
        except Exception:  # noqa: BLE001 - 定时器可能在界面收尾阶段触发
            return
        bar.update_stats(self._agent.context_stats())

    async def _handle_event(self, event: AgentEvent, chat: ChatView) -> None:
        """把 core 事件翻译成界面变化。"""
        if isinstance(event, TextDeltaEvent):
            self._pending += event.text
            await self._flush_chat(chat)
        elif isinstance(event, MessageCompleteEvent):
            await self._flush_chat(chat, force=True)
        elif isinstance(event, ToolCallEvent):
            self._set_status(f"调用工具 {event.name}…")
            await chat.add_tool_call(event.name, event.arguments)
        elif isinstance(event, ToolResultEvent):
            await chat.add_tool_result(event.name, event.content, event.is_error)
        elif isinstance(event, StatusEvent):
            self._set_status(event.message, "⚙")
        elif isinstance(event, ErrorEvent):
            await chat.add_error(event.message)
        elif isinstance(event, TurnCompleteEvent):
            self._set_status("就绪", "●")
        elif isinstance(event, ContextStatsEvent):
            self._render_context()
        elif isinstance(event, ContextWarningEvent):
            self._set_status(event.message, "!")

    async def _flush_chat(self, chat: ChatView, force: bool = False) -> None:
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

    # ---------- 首次启动欢迎提示 ----------

    # ---------- MCP 异步加载与边栏 ----------

    async def _load_mcp(self) -> None:
        """后台加载 MCP 服务器，完成后动态刷新边栏。"""
        try:
            manager = await attach_mcp_async(self._agent.tools, self._config)
            self._mcp = manager
            self._refresh_mcp_sidebar()
            if manager.connected_servers():
                self._set_status(f"MCP 已连接 {len(manager.connected_servers())} 个服务器", "●")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"MCP 加载失败: {exc}", "!")
            self.query_one("#mcp", McpSidebar).update(
                f"MCP 服务器\n  （加载失败: {exc}）"
            )

    def _refresh_mcp_sidebar(self) -> None:
        """刷新右侧 MCP 边栏内容。"""
        if self._mcp is None:
            return
        self.query_one("#mcp", McpSidebar).update_servers(
            self._mcp.connected_servers(),
            self._mcp.server_tools(),
            self._mcp.errors,
        )


class TUIFrontend(Frontend):
    """Textual 前端适配器。"""

    name = "tui"

    def __init__(self, config=None) -> None:
        self._config = config

    def run(self, agent: Agent, config=None) -> None:
        """启动终端界面。"""
        XAgentApp(agent=agent, config=config if config is not None else self._config).run()