"""配置缺失提示对话框：config.ini 不存在时自动生成示例配置并弹窗告知用户。"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Static

from ui.base import ensure_utf8_io


class ConfigNoticeApp(App):
    """显示一段提示文本并要求用户确认退出的轻量对话框。"""

    CSS = """
    Screen {
        align: center middle;
    }
    #box {
        width: 78;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #box-message {
        content-align: left top;
        margin-bottom: 1;
        height: auto;
    }
    #box-button {
        width: 14;
        margin: 1 2 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "close_dialog", "关闭", priority=True),
        Binding("enter", "close_dialog", "关闭", priority=True),
    ]

    def __init__(self, message: str, config_path=None) -> None:
        super().__init__()
        self._message = message
        self._config_path = config_path

    def compose(self) -> ComposeResult:
        self.sub_title = "xAgent 配置缺失"
        yield Static(
            self._message
            + (
                f"\n\n文件位置：{self._config_path}"
                if self._config_path
                else ""
            ),
            id="box",
            classes="notify-box",
        )
        yield Static(
            "\n\n⚠ 直接回车或按 Esc 退出。修改 config.ini 后重新运行程序即可正常使用。",
            classes="notify-hint",
        )

    def action_close_dialog(self) -> None:
        self.exit()


def run_notice_dialog(message: str, config_path=None) -> int:
    """运行配置提示对话框，返回退出码。"""
    ensure_utf8_io()
    ConfigNoticeApp(message, config_path).run()


__all__ = ["ConfigNoticeApp", "run_notice_dialog"]