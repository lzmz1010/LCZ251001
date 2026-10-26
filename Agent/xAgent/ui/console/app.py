"""控制台前端：最简参考实现，用于验证 core 与 UI 的分离。"""

from __future__ import annotations

import asyncio

from core.agent import Agent
from core.events import (
    ErrorEvent,
    MessageCompleteEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from ui.base import Frontend, ensure_utf8_io


class ConsoleFrontend(Frontend):
    """标准输入输出实现的对话界面。"""

    name = "console"

    async def _conversation(self, agent: Agent) -> None:
        loop = asyncio.get_running_loop()
        print(f"xAgent 控制台 · 模型 {agent.model_name}")
        print("直接输入内容按回车；按 Ctrl+C 退出。\n")
        while True:
            try:
                user_input = await loop.run_in_executor(None, input, "你: ")
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input.strip():
                continue
            await self._run_turn(agent, user_input)
            print()

    async def _run_turn(self, agent: Agent, user_input: str) -> None:
        print("AI: ", end="", flush=True)
        async for event in agent.stream_turn(user_input):
            if isinstance(event, TextDeltaEvent):
                print(event.text, end="", flush=True)
            elif isinstance(event, ToolCallEvent):
                print(f"\n[工具] {event.name}({event.arguments})", flush=True)
            elif isinstance(event, ToolResultEvent):
                prefix = "[错误]" if event.is_error else "[结果]"
                print(f"{prefix} {event.content}", flush=True)
            elif isinstance(event, ErrorEvent):
                print(f"\n[错误] {event.message}", flush=True)
            elif isinstance(event, MessageCompleteEvent):
                print(flush=True)
            elif isinstance(event, TurnCompleteEvent):
                print(flush=True)

    def run(self, agent: Agent) -> None:
        """启动控制台对话循环。"""
        ensure_utf8_io()
        try:
            asyncio.run(self._conversation(agent))
        except KeyboardInterrupt:
            print("\n已退出对话。")
