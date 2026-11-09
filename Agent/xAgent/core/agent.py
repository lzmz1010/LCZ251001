"""Agent 主循环。

这是 core 的核心业务逻辑：接收用户输入 → 请求模型 → 如有工具调用则执行并回传 →
再次请求模型，直到得到最终回答。整个过程通过事件流输出，界面只负责渲染。

Agent 还负责两个上下文管理职责：

- 每轮结束统计上下文占用（优先用模型 API 返回的 ``prompt_tokens``，否则估算）；
  达到 ``warn_ratio``（默认 70%）时通过事件警告，并暂停接收普通用户提示词。
- 提供 ``/compact`` 压缩：先把原始上下文归档到 ``.agents/context/``，
  再用 LLM 生成约 5000 tokens 的摘要替换历史（系统提示词与工具定义保留）。
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator, Callable, Sequence

from core.config import ContextConfig
from core.context import (
    COMPRESSION_PROMPT,
    ContextArchiver,
    ContextStats,
    CompressionResult,
    render_readable_history,
)
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
    UserMessageEvent,
)
from core.llm.base import LLMClient
from core.models import Message, ToolCall
from core.session import Session
from core.tokens import estimate_session_tokens
from core.tools.base import ToolSpec
from core.tools.registry import ToolRegistry


class Agent:
    """带有工具调用能力的对话代理。"""

    #: 模型返回“空响应”（无文本、无工具调用）时的重试次数。
    #: 本地服务器（LM Studio 等）偶发返回空补全会话结束，重试可显著降低
    #: 「agent 不回答」的概率；重试仍为空时再向用户明确报错。
    EMPTY_RESPONSE_RETRIES = 2

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        session: Session | None = None,
        max_tool_rounds: int = 8,
        before_turn: Callable[[], None] | None = None,
        context_config: ContextConfig | None = None,
        agents_config=None,
        empty_response_retries: int | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._session = session or Session()
        self._max_tool_rounds = max_tool_rounds
        self._before_turn = before_turn
        self._context_config = context_config or ContextConfig()
        self._agents_config = agents_config
        self._empty_response_retries = (
            empty_response_retries
            if empty_response_retries is not None
            else self.EMPTY_RESPONSE_RETRIES
        )
        self._archiver = ContextArchiver(
            self._context_config.archive_dir,
            recall_limit=self._context_config.recall_limit,
            snippet_max_chars=self._context_config.snippet_max_chars,
        )
        #: 最近一次由模型 API 实测（非估算）的 prompt token 数。
        #: 压缩成功后会被清空，避免旧的高占用值造成误拦截。
        self._measured_tokens: int | None = None
        #: 是否正在压缩上下文（压缩期间不接受普通任务）。
        self._compressing = False

    @property
    def session(self) -> Session:
        """当前会话上下文。"""
        return self._session

    @property
    def model_name(self) -> str:
        """当前模型名称（供界面展示）。"""
        return self._llm.model_name

    @property
    def tools(self) -> ToolRegistry:
        """当前工具注册表。"""
        return self._tools

    @property
    def archiver(self) -> ContextArchiver:
        """上下文归档器（保存/检索原始记录）。"""
        return self._archiver

    @property
    def is_compressing(self) -> bool:
        """是否正在执行上下文压缩。"""
        return self._compressing

    def tool_specs(self) -> Sequence[ToolSpec]:
        """可提供给模型的工具描述。"""
        return self._tools.specs()

    # ---------- 上下文统计与输入控制 ----------

    def context_stats(self) -> ContextStats:
        """计算当前上下文的占用情况。"""
        # 优先使用模型 API 返回的真实 token 数，没有则用本地估算
        used = self._measured_tokens
        if used is None:
            used = estimate_session_tokens(self._session.messages)
        window = self._context_config.context_window
        ratio = used / window if window > 0 else 0.0
        blocked = ratio >= self._context_config.warn_ratio
        return ContextStats(
            used_tokens=used,
            window_tokens=window,
            ratio=ratio,
            window_is_default=self._context_config.window_is_default,
            blocked=blocked,
        )

    def can_accept_input(self) -> bool:
        """是否允许接收新的普通用户提示词。"""
        if self._compressing:
            return False
        return not self.context_stats().blocked

    # ---------- 会话生命周期 ----------

    def inject_agents_md(self) -> Message | None:
        """注入项目约定 AGENTS.md（一次注入，全程复用）。

        在会话首次加载时调用：若当前项目目录存在 AGENTS.md，就把其内容作为
        一条 user 消息插入到系统提示词之后、全部用户对话之前，并随会话一起
        持久化（/save、/resume、/compact 归档均会保留）。已注入过则跳过，
        避免 /new 或重复调用造成重复注入。
        """
        agents_config = self._agents_config
        if agents_config is None or not agents_config.inject:
            return None
        marker = f"【项目约定 {agents_config.md_file}】"
        if any(m.content.startswith(marker) for m in self._session.messages):
            return None
        path = Path.cwd() / agents_config.md_file
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if not content.strip():
            return None
        return self._session.insert_context(Message(role="user", content=f"{marker}\n{content}"))

    def reset_session(self) -> None:
        """清空会话历史，保留系统提示词，并重新注入 AGENTS.md（供 /new）。"""
        self._session.clear()
        self._measured_tokens = None
        self.inject_agents_md()

    # ---------- 上下文压缩 ----------

    async def compress(self) -> CompressionResult:
        """手动触发一次上下文压缩（``/compact``）。

        流程：归档原始上下文 → LLM 生成摘要 → 用摘要替换历史。
        任何一步失败都不会改动原有会话，可重新执行。
        """
        if self._compressing:
            return CompressionResult(
                success=False, message="上一次压缩仍在进行中，请稍候"
            )

        self._compressing = True
        try:
            # 1) 先保存完整原始上下文，保存成功才继续
            archive_id = self._archiver.save_session(self._session)

            # 2) 构造压缩请求：系统提示词为压缩任务，用户消息为易读历史
            history = render_readable_history(self._session.messages)
            messages = [
                Message(role="system", content=COMPRESSION_PROMPT),
                Message(role="user", content=history),
            ]
            parts: list[str] = []
            async for chunk in self._llm.stream_chat(messages):
                if chunk.content:
                    parts.append(chunk.content)
            summary = "".join(parts)
            if not summary.strip():
                raise RuntimeError("模型返回的摘要是空的")

            # 3) 用摘要替换历史，保留系统提示词与工具定义
            self._session.replace_history_with_summary(summary, archive_id)

            # 重置实测 token 数，避免旧的高占用值继续造成输入拦截
            self._measured_tokens = None
            used_estimate = estimate_session_tokens(self._session.messages)
            return CompressionResult(
                success=True,
                message=(
                    f"压缩完成，摘要约 {used_estimate} tokens，"
                    f"原始上下文已归档为 {archive_id}。"
                ),
                archive_id=archive_id,
                summary=summary,
            )
        except Exception as exc:  # noqa: BLE001 - 压缩失败保留原有上下文并报告
            return CompressionResult(
                success=False,
                message=f"压缩失败，已保留原有上下文: {exc}",
                archive_id=getattr(exc, "_archive_id", None),
            )
        finally:
            self._compressing = False

    # ---------- 主循环 ----------

    async def stream_turn(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """执行一轮对话，以事件流的形式输出全部中间过程。

        上下文占用达到阈值时暂停接收普通提示词；缩紧结束后自动恢复。
        """
        if self._before_turn is not None:
            self._before_turn()

        if self._compressing:
            yield ErrorEvent(message="正在压缩上下文，请先等待压缩完成")
            return

        if not self.can_accept_input():
            stats = self.context_stats()
            yield ContextWarningEvent(
                ratio=stats.ratio,
                message=(
                    f"上下文已占用 {stats.ratio * 100:.0f}%（阈值 {self._context_config.warn_ratio * 100:.0f}%），"
                    "已暂停接收新输入；请先输入 /compact 完成上下文压缩。"
                ),
            )
            return

        user_message = self._session.add_user(user_input)
        yield UserMessageEvent(text=user_message.content)

        final_text = ""
        rounds = 0
        empty_count = 0
        while True:
            if rounds >= self._max_tool_rounds:
                yield ErrorEvent(
                    message=f"已达到最大工具调用轮数 ({self._max_tool_rounds})，本轮提前结束"
                )
                break
            rounds += 1

            content_parts: list[str] = []
            tool_calls: dict[int, ToolCall] = {}

            async for chunk in self._llm.stream_chat(
                messages=self._session.messages,
                tools=self._tools.specs(),
            ):
                if chunk.content:
                    content_parts.append(chunk.content)
                    yield TextDeltaEvent(text=chunk.content)
                for delta in chunk.tool_calls:
                    call = tool_calls.get(delta.index)
                    if call is None:
                        call = ToolCall(
                            id=delta.id or "", name=delta.name or "", arguments=""
                        )
                        tool_calls[delta.index] = call
                    if delta.id:
                        call.id = delta.id
                    if delta.name:
                        call.name = delta.name
                    if delta.arguments:
                        call.arguments += delta.arguments

            # 主模型失败回退到备用模型时，把提示输出为状态事件
            consume_notice = getattr(self._llm, "consume_notice", None)
            if consume_notice is not None:
                notice = consume_notice()
                if notice:
                    yield StatusEvent(message=notice)

            content = "".join(content_parts)
            ordered_calls = list(tool_calls.values())

            if not content and not ordered_calls:
                # 模型返回“空响应”（本地服务器偶发，例如只输出了思考分词但无正文）。
                # 空响应不算一轮回答也不写入历史，直接重试，避免「agent 不回答」。
                empty_count += 1
                if empty_count <= self._empty_response_retries:
                    yield StatusEvent(
                        message=(
                            f"模型未返回任何内容，正在重试 "
                            f"({empty_count}/{self._empty_response_retries})…"
                        )
                    )
                    continue
                yield ErrorEvent(
                    message=(
                        "模型连续多次未返回任何内容，本轮没有生成回答。"
                        "请换一种问法重试；若对话已经很长，也可先输入 /compact 压缩上下"
                        "文后再继续。"
                    )
                )
                break

            self._session.add_assistant(content, ordered_calls)
            yield MessageCompleteEvent(
                text=content, has_tool_calls=bool(ordered_calls)
            )

            if not ordered_calls:
                final_text = content
                break

            for call in ordered_calls:
                yield ToolCallEvent(
                    call_id=call.id, name=call.name, arguments=call.arguments
                )
            for call in ordered_calls:
                yield StatusEvent(message=f"正在执行工具 {call.name}")
                result = await self._tools.execute_async(call.name, call.arguments)
                self._session.add_tool_result(call.id, call.name, result.content)
                yield ToolResultEvent(
                    call_id=call.id,
                    name=call.name,
                    content=result.content,
                    is_error=result.is_error,
                )

        yield TurnCompleteEvent(text=final_text)

        # 每轮 LLM 响应（用户提示词）结束后更新上下文统计
        actual = self._llm.last_prompt_tokens
        if actual is not None:
            self._measured_tokens = actual

        stats = self.context_stats()
        yield ContextStatsEvent(
            used_tokens=stats.used_tokens,
            window_tokens=stats.window_tokens,
            ratio=stats.ratio,
            window_is_default=stats.window_is_default,
            blocked=stats.blocked,
        )
        if stats.blocked:
            yield ContextWarningEvent(
                ratio=stats.ratio,
                message=(
                    f"上下文已占用 {stats.ratio * 100:.0f}%（阈值 {self._context_config.warn_ratio * 100:.0f}%），"
                    "建议立即执行 /compact 压缩上下文。"
                ),
            )

    async def ask(self, user_input: str) -> str:
        """执行一轮对话并返回最终文本（非流式便捷接口）。"""
        final_text = ""
        async for event in self.stream_turn(user_input):
            if isinstance(event, TurnCompleteEvent):
                final_text = event.text
        return final_text


__all__ = ["Agent"]