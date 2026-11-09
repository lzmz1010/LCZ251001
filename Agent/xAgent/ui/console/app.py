"""控制台前端：最简参考实现，用于验证 core 与 UI 的分离。

支持斜杠命令：/new /save /resume /clear /compact /help /quit（简化版，
无 TUI 的补全面板与选择面板；/resume 列出会话编号后按编号恢复）。
"""

from __future__ import annotations

import asyncio

from core.agent import Agent
from core.bootstrap import attach_mcp_async
from core.events import (
    ContextStatsEvent,
    ContextWarningEvent,
    ErrorEvent,
    MessageCompleteEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from core.sessions import SessionStore
from ui.base import Frontend, ensure_utf8_io


def _format_k(tokens: int) -> str:
    """把 token 数转成界面友好的「k」显示。"""
    if tokens < 1000:
        return str(tokens)
    if tokens < 10000:
        return f"{tokens / 1000:.1f}k"
    return f"{tokens // 1000}k"


def _context_hint(agent: Agent) -> str:
    """当前上下文的占用提示。"""
    stats = agent.context_stats()
    default = "（默认）" if stats.window_is_default else ""
    return (
        f"上下文 {_format_k(stats.used_tokens)} / {_format_k(stats.window_tokens)}"
        f" · 已占用 {stats.ratio * 100:.0f}%{default}"
    )


class ConsoleFrontend(Frontend):
    """标准输入输出实现的对话界面。"""

    name = "console"

    def __init__(self, config=None) -> None:
        self._config = config

    async def _conversation(self, agent: Agent) -> None:
        loop = asyncio.get_running_loop()
        store = SessionStore(
            (self._config.sessions.dir if self._config is not None else None)
        )
        print(f"xAgent 控制台 · 模型 {agent.model_name}")
        print(f"[上下文] {_context_hint(agent)}")
        print("直接输入内容按回车；输入 /compact 压缩上下文；输入 /help 查看命令；按 Ctrl+C 退出。")
        print()
        await self._load_mcp(agent)
        while True:
            try:
                user_input = await loop.run_in_executor(None, input, "你: ")
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input.strip():
                continue
            user_input = user_input.strip()
            if user_input.startswith("/"):
                await self._dispatch(agent, store, user_input)
                continue
            if not agent.can_accept_input():
                print(f"[系统] {_context_hint(agent)}，已暂停接收新输入，请先输入 /compact 压缩。")
                print()
                continue
            await self._run_turn(agent, user_input)
            print(f"[上下文] {_context_hint(agent)}")
            print()

    async def _load_mcp(self, agent: Agent) -> None:
        """异步加载 MCP（在后台线程连接），完成后打印状态。"""
        try:
            manager = await attach_mcp_async(agent.tools, self._config)
            servers = manager.connected_servers()
            if servers:
                print(f"[MCP] 已连接 {len(servers)} 个服务器: {', '.join(servers)}")
                for name, tools in manager.server_tools().items():
                    print(f"[MCP]   {name}: {', '.join(tools) or '（无工具）'}")
            else:
                print("[MCP] 未连接任何 MCP 服务器（当前目录没有 .mcp.json，或全部连接失败）")
            if manager.errors:
                for error in manager.errors:
                    print(f"[MCP] 错误: {error}")
        except Exception as exc:  # noqa: BLE001
            print(f"[MCP] 加载失败: {exc}")
        print()

    async def _dispatch(
        self, agent: Agent, store: SessionStore, line: str
    ) -> None:
        """分发斜杠命令。"""
        name, _, arg = line[1:].partition(" ")
        name = name.strip().lower()
        if name == "quit":
            raise SystemExit(0)
        if name == "help":
            print(
                "可用命令：/new 新建(自动保存旧会话) /save 保存 /resume 恢复 "
                "/clear 清空 /compact 压缩 /skills 技能 /help 帮助 /quit 退出"
            )
            print()
            return
        if name == "save":
            meta = await asyncio.to_thread(store.save, agent.session)
            print(f"[系统] 已保存会话 {meta.id}（{meta.count} 条消息）")
            print()
            return
        if name == "new":
            if any(m.role == "user" for m in agent.session.messages):
                meta = await asyncio.to_thread(store.save, agent.session)
                print(f"[系统] 原会话已保存为 {meta.id}")
            agent.reset_session()
            print("[系统] 已新建会话")
            print()
            return
        if name == "resume":
            metas = store.list()
            if not metas:
                print("[系统] 暂无已保存的会话")
                print()
                return
            print("[系统] 历史会话：")
            for meta in metas:
                print(f"  {meta.id}  {meta.saved_at}  「{meta.title}」（{meta.count} 条）")
            if arg:
                await self._resume(agent, store, arg.strip())
            else:
                print("  用法: /resume <会话编号>")
            print()
            return
        if name == "clear":
            await self._chat_clear(agent)
            return
        if name == "compact":
            await self._run_compact(agent)
            return
        print(f"[系统] 未知命令 /{name}，输入 /help 查看可用命令")
        print()

    async def _resume(self, agent: Agent, store: SessionStore, session_id: str) -> None:
        try:
            messages = await asyncio.to_thread(store.load, session_id)
            agent.session.restore_messages(messages)
            print(f"[系统] 已恢复会话 {session_id}（{len(messages)} 条消息）")
        except Exception as exc:  # noqa: BLE001
            print(f"[系统] 恢复会话失败: {exc}")
        print()

    async def _chat_clear(self, agent: Agent) -> None:
        agent.session.clear()
        print("[系统] 已清空对话")
        print()

    async def _run_compact(self, agent: Agent) -> None:
        print("[系统] 开始压缩上下文…")
        result = await agent.compress()
        if result.success:
            print(f"[系统] 上下文压缩完成，归档编号 {result.archive_id}")
            print(f"[系统] {result.message}")
        else:
            print(f"[系统] 上下文压缩失败，已保留原有上下文：{result.message}")
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
            elif isinstance(event, ContextStatsEvent):
                print(f"\n[上下文] {_format_k(event.used_tokens)} / {_format_k(event.window_tokens)} · {event.ratio * 100:.0f}%", flush=True)
            elif isinstance(event, ContextWarningEvent):
                print(f"\n[警告] {event.message}", flush=True)
            elif isinstance(event, MessageCompleteEvent):
                print(flush=True)
            elif isinstance(event, TurnCompleteEvent):
                print(flush=True)

    def run(self, agent: Agent, config=None) -> None:
        """启动控制台对话循环。"""
        if config is not None:
            self._config = config
        ensure_utf8_io()
        try:
            asyncio.run(self._conversation(agent))
        except KeyboardInterrupt:
            print("\n已退出对话。")
        except SystemExit:
            print("\n已退出对话。")


__all__ = ["ConsoleFrontend"]