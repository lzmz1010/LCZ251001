"""TUI 组件：消息气泡、消息列表、输入区、状态栏。

所有组件只负责渲染，不包含任何业务判断；
数据全部来自 core 产生的事件。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, ListItem, ListView, Markdown, Static, TextArea

ROLE_TITLES = {
    "user": "你",
    "assistant": "助手",
    "tool": "工具",
    "system": "系统",
}


def format_k(tokens: int) -> str:
    """把 token 数转成界面友好的「k」显示（<1k 时显示原值）。"""
    if tokens < 1000:
        return str(tokens)
    if tokens < 10000:
        return f"{tokens / 1000:.1f}k"
    return f"{tokens // 1000}k"


class ContextBar(Static):
    """上下文占用信息栏（醒目位置展示）。"""

    def update_stats(self, stats) -> None:
        used = format_k(stats.used_tokens)
        window = format_k(stats.window_tokens)
        percent = f"{stats.ratio * 100:.0f}%"
        default_hint = "「默认」" if stats.window_is_default else ""
        warning = " ⚠ 请执行 /compact 压缩上下文" if stats.blocked else ""
        self.update(f"上下文 {used} / {window} · 已占用 {percent}{default_hint}{warning}")


class MessageBubble(Vertical):
    """一条对话气泡，支持流式追加文本。"""

    def __init__(self, role: str, text: str = "") -> None:
        super().__init__(classes=f"bubble bubble-{role}")
        self._role = role
        self._text = text
        self._body: Markdown | None = None

    def compose(self) -> ComposeResult:
        yield Label(ROLE_TITLES.get(self._role, self._role), classes="bubble-title")
        self._body = Markdown(self._text)
        yield self._body

    @property
    def text(self) -> str:
        """当前气泡内的完整文本。"""
        return self._text

    def append_text(self, text: str) -> None:
        """追加文本（流式输出场景）。"""
        self._text += text
        if self._body is not None:
            self._body.update(self._text)


class _CompactBubble(Vertical):
    """工具类气泡的紧凑基类：默认折叠成一行小字，点击展开/收起。"""

    MAX_SUMMARY = 36

    def __init__(self, name: str, content: str, is_error: bool, prefix: str) -> None:
        classes = "bubble bubble-tool compact"
        if is_error:
            classes += " bubble-error"
        super().__init__(classes=classes)
        self._name = name
        self._content = content
        self._is_error = is_error
        self._prefix = prefix
        self._expanded = True
        self._detail: Static | None = None

    @property
    def caption(self) -> str:
        """一行摘要。"""
        head = self._one_line(self._content)
        head = head or "（空）"
        return f"{self._prefix} {self._name}  {head}"

    @staticmethod
    def _one_line(text: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line if len(line) <= _CompactBubble.MAX_SUMMARY else line[: _CompactBubble.MAX_SUMMARY] + "…"
        return ""

    def compose(self) -> ComposeResult:
        yield Static(self.caption, classes="compact-summary")
        if not self._is_error:
            self._detail = Static(self._content, classes="compact-detail")
            self._detail.display = True
            yield self._detail

    async def on_click(self) -> None:
        """点击未出错的工具结果气泡时，展开/收起详细内容。"""
        if self._detail is None:
            return
        self._expanded = not self._expanded
        self._detail.display = self._expanded
        self.refresh()


class ToolCallBubble(_CompactBubble):
    """模型请求调用工具时的提示气泡。"""

    def __init__(self, name: str, arguments: str = "") -> None:
        super().__init__(name, arguments, False, "调用")


class ToolResultBubble(_CompactBubble):
    """工具执行结果气泡。"""

    def __init__(self, name: str, content: str = "", is_error: bool = False) -> None:
        super().__init__(name, content, is_error, "出错" if is_error else "结果")


class ErrorBubble(Vertical):
    """错误提示气泡。"""

    def __init__(self, message: str) -> None:
        super().__init__(classes="bubble bubble-error")
        self._message = message

    def compose(self) -> ComposeResult:
        yield Label("出错", classes="bubble-title")
        yield Static(self._message, classes="bubble-body")


class ChatView(VerticalScroll):
    """消息列表容器。"""

    async def add_message(self, role: str, text: str = "") -> MessageBubble:
        """追加一条消息气泡。"""
        bubble = MessageBubble(role, text)
        await self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    async def add_tool_call(self, name: str, arguments: str = "") -> ToolCallBubble:
        """追加一条工具调用气泡。"""
        bubble = ToolCallBubble(name, arguments)
        await self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    async def add_tool_result(
        self, name: str, content: str = "", is_error: bool = False
    ) -> ToolResultBubble:
        """追加一条工具结果气泡。"""
        bubble = ToolResultBubble(name, content, is_error)
        await self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    async def add_error(self, message: str) -> ErrorBubble:
        """追加一条错误气泡。"""
        bubble = ErrorBubble(message)
        await self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    async def clear(self) -> None:
        """清空所有消息。"""
        await self.remove_children()


class Composer(Horizontal):
    """底部输入区。"""

    def compose(self) -> ComposeResult:
        yield TextArea(
            "",
            id="input",
            soft_wrap=True,
            show_line_numbers=False,
            placeholder="输入药品、术语或症状问题，Ctrl+Enter 发送",
        )
        yield Button("发送", id="send", variant="primary")

    @property
    def text(self) -> str:
        """输入框中的文本。"""
        return self.query_one("#input", TextArea).text

    def clear(self) -> None:
        """清空输入框。"""
        self.query_one("#input", TextArea).clear()

    def focus_input(self) -> None:
        """聚焦到输入框。"""
        self.query_one("#input", TextArea).focus()


class StatusBar(Static):
    """底部状态栏。"""

    def set_status(self, message: str, icon: str = "") -> None:
        """更新状态文本。"""
        self.update(f"{icon} {message}" if icon else message)


class SlashPalette(Vertical):
    """斜杠命令补全面板：输入以 ``/`` 开头时弹出，↑↓ 选择、Enter 执行、Esc 关闭。"""

    def __init__(self, commands: list[tuple[str, str]]) -> None:
        super().__init__(id="palette", classes="overlay-panel")
        self._commands = list(commands)
        self._list: ListView | None = None
        self.display = False

    @property
    def list(self) -> ListView:
        """补全列表。"""
        assert self._list is not None
        return self._list

    def compose(self) -> ComposeResult:
        yield Label(
            "斜杠命令（↑↓ 选择 · Enter 执行 · Esc 取消 · 继续输入可过滤）",
            classes="overlay-title",
        )
        self._list = ListView(classes="overlay-list")
        yield self._list

    def refresh_items(self, filter_text: str) -> list[tuple[str, str]]:
        """依据输入前缀刷新列表项，返回匹配的命令列表。"""
        prefix = (filter_text or "").strip().lower()
        matches = [
            (name, hint)
            for name, hint in self._commands
            if prefix in name.lower()
        ]
        self._list.clear()
        for name, hint in matches:
            item = ListItem(
                Label(f" {name:<14}{hint}", classes="overlay-item")
            )
            item.data = {"command": name, "hint": hint}
            self._list.append(item)
        self._matched = bool(matches)
        return matches


class SessionListPanel(Vertical):
    """历史会话列表面板：↑↓ 选择、Enter 恢复、Esc 取消。"""

    def __init__(self) -> None:
        super().__init__(id="session-list", classes="overlay-panel")
        self._list: ListView | None = None
        self.display = False

    @property
    def list(self) -> ListView:
        """会话列表。"""
        assert self._list is not None
        return self._list

    def compose(self) -> ComposeResult:
        yield Label(
            "历史会话（↑↓ 选择 · Enter 恢复 · Esc 取消）",
            classes="overlay-title",
        )
        self._list = ListView(classes="overlay-list")
        yield self._list

    def refresh_items(self, metas) -> None:
        """用会话摘要填充列表。"""
        self._list.clear()
        for meta in metas:
            item = ListItem(
                Label(
                    f" {meta.id}  {meta.saved_at}\n   {meta.title}  （{meta.count} 条消息）",
                    classes="overlay-item",
                )
            )
            item.data = {"session_id": meta.id, "title": meta.title}
            self._list.append(item)


class McpSidebar(Static):
    """右侧边栏：展示已连接的 MCP 服务器与该服务器暴露的工具。"""

    def __init__(self) -> None:
        super().__init__("MCP 服务器\n  （加载中…）", id="mcp", classes="mcp-sidebar")

    def update_servers(self, servers: list[str], tools_by_server: dict, errors: list[str]) -> None:
        """渲染服务器与工具列表。"""
        lines = ["MCP 服务器"]
        if not servers:
            lines.append("\n  （已连接: 0）")
        for name in servers:
            tools = tools_by_server.get(name, [])
            lines.append(f"\n  ✓ {name}\n     连接正常")
            if tools:
                lines.append(f"     工具({len(tools)}):")
                lines.append(f"       {'、'.join(tools)}")
            else:
                lines.append("     工具: （无）")
        if errors:
            lines.append("\n  ✗ 错误:")
            for error in errors:
                lines.append(f"    {error[:60]}")
        self.update("\n".join(lines))
