"""``python -m ui.tui`` 入口：直接启动终端界面。"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许以 `python -m ui.tui` 从项目根目录启动
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.bootstrap import attach_mcp, build_agent  # noqa: E402
from core.config import load_config  # noqa: E402
from ui.tui.app import TUIFrontend  # noqa: E402


def main() -> None:
    """读取配置并启动 TUI。"""
    config = load_config()
    agent = build_agent(config)
    attach_mcp(agent.tools)
    TUIFrontend().run(agent)


if __name__ == "__main__":
    main()
