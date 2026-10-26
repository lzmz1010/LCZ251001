"""前端契约与前端注册表。

任何新界面（TUI / Web / Desktop / Mobile）只需要：

1. 继承 ``Frontend``，实现 ``run(agent)``；
2. 在自己的模块中消费 ``agent.stream_turn()`` 产生的事件流；
3. 通过 ``registry.register("web", ...)`` 注册，即可被统一入口 ``--ui web`` 调起。
"""

from __future__ import annotations

import importlib
import sys
from abc import ABC, abstractmethod
from typing import Any, Callable, ClassVar

from core.agent import Agent

FrontendFactory = Callable[..., "Frontend"]


def ensure_utf8_io() -> None:
    """把标准输入输出统一到 UTF-8，避免中文在非 UTF-8 终端上乱码。"""
    for stream in (sys.stdout, sys.stdin):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - 取决于运行环境
            pass


class Frontend(ABC):
    """所有前端的统一接口。"""

    name: ClassVar[str] = "frontend"

    @abstractmethod
    def run(self, agent: Agent) -> None:
        """启动界面并与 Agent 交互，直到用户主动退出。"""


class FrontendRegistry:
    """前端注册表：按名称创建前端实例。"""

    def __init__(self) -> None:
        self._factories: dict[str, FrontendFactory] = {}

    def register(self, name: str, factory: FrontendFactory) -> None:
        """注册一个前端工厂函数。"""
        if name in self._factories:
            raise ValueError(f"前端 {name} 已注册")
        self._factories[name] = factory

    def names(self) -> list[str]:
        """已注册的前端名称。"""
        return list(self._factories)

    def create(self, name: str, **kwargs: Any) -> Frontend:
        """按名称创建前端实例。"""
        factory = self._factories.get(name)
        if factory is None:
            raise KeyError(f"未知前端: {name}（可用: {', '.join(self.names())}）")
        return factory(**kwargs)


def _create_tui(**kwargs: Any) -> Frontend:
    """延迟导入 Textual 前端，避免其它前端强制依赖 textual。"""
    module = importlib.import_module("ui.tui.app")
    return module.TUIFrontend(**kwargs)


def _create_console(**kwargs: Any) -> Frontend:
    """延迟导入控制台前端。"""
    module = importlib.import_module("ui.console.app")
    return module.ConsoleFrontend(**kwargs)


registry = FrontendRegistry()
registry.register("tui", _create_tui)
registry.register("console", _create_console)


def create_frontend(name: str, **kwargs: Any) -> Frontend:
    """按名称创建前端实例（使用全局注册表）。"""
    return registry.create(name, **kwargs)
