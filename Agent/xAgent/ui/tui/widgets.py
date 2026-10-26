"""TUI 组件：消息气泡、消息列表、输入区、状态栏。

所有组件只负责渲染，不包含任何业务判断；
数据全部来自 core 产生的事件。
"""

from __future__ import annotations

import json

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Markdown, Static, TextArea

ROLE_TITLES = {
    "user": "你",
    "assistant": "AI",
    "tool": "工具",
    "system": "系统",
}


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


class ToolCallBubble(Vertical):
    """模型请求调用工具时的提示气泡。"""

    def __init__(self, name: str, arguments: str = "") -> None:
        super().__init__(classes="bubble bubble-tool")
        self._name = name
        self._arguments = arguments

    def compose(self) -> ComposeResult:
        yield Label(f"调用工具：{self._name}", classes="bubble-title")
        yield Static(self._format_arguments(), classes="bubble-body")

    def _format_arguments(self) -> str:
        raw = (self._arguments or "").strip()
        if not raw:
            return "（无参数）"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        return json.dumps(data, ensure_ascii=False, indent=2)


class ToolResultBubble(Vertical):
    """工具执行结果气泡。"""

    def __init__(self, name: str, content: str = "", is_error: bool = False) -> None:
        classes = "bubble bubble-tool bubble-error" if is_error else "bubble bubble-tool"
        super().__init__(classes=classes)
        self._name = name
        self._content = content
        self._is_error = is_error

    def compose(self) -> ComposeResult:
        title = "工具出错" if self._is_error else "工具结果"
        yield Label(f"{title}：{self._name}", classes="bubble-title")
        yield Static(self._content, classes="bubble-body")


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
            placeholder="输入内容，Ctrl+Enter 发送",
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
