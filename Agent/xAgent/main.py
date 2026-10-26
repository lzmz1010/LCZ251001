"""xAgent 统一入口（组合根）。

职责：
1. 解析命令行参数；
2. 装载配置；
3. 装配 core（Agent）；
4. 创建并启动所选前端。

新增前端（例如 Web、Desktop）时，只需在 ``ui`` 包下实现 ``Frontend`` 并注册，
本文件无需改动。

用法::

    python main.py                     # 启动 Textual 终端界面
    python main.py --ui console        # 启动控制台界面
    python main.py --ui console --model qwen2.5-7b-instruct
    python main.py --list-ui           # 查看可用前端
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许从任意目录执行 `python /path/to/xAgent/main.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.bootstrap import build_agent  # noqa: E402
from core.config import load_config  # noqa: E402
from core.errors import ConfigError  # noqa: E402
from ui.base import create_frontend, ensure_utf8_io, registry  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="xagent", description="xAgent - core 与 UI 分离的 LLM Agent"
    )
    parser.add_argument(
        "--ui",
        "-u",
        default="tui",
        help=f"前端类型，可选: {', '.join(registry.names())}",
    )
    parser.add_argument("--config", "-c", default=None, help="config.ini 路径")
    parser.add_argument("--model", "-m", default=None, help="覆盖配置中的模型名称")
    parser.add_argument("--base-url", default=None, help="覆盖配置中的 base_url")
    parser.add_argument("--api-key", default=None, help="覆盖配置中的 api_key")
    parser.add_argument(
        "--list-ui", action="store_true", help="列出所有可用前端后退出"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """程序主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    ensure_utf8_io()

    if args.list_ui:
        print("可用前端:")
        for name in registry.names():
            print(f"  - {name}")
        return 0

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    config = config.with_overrides(
        llm_model=args.model,
        llm_base_url=args.base_url,
        llm_api_key=args.api_key,
    )

    try:
        frontend = create_frontend(args.ui)
    except KeyError as exc:
        print(f"前端错误: {exc.args[0]}", file=sys.stderr)
        return 2

    agent = build_agent(config)
    frontend.run(agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
