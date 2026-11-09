"""组合根：把 core 的各个零件装配成一个可直接使用的 Agent。

前端（TUI / Web / Desktop）只依赖这里产出的 ``Agent`` 对象，
新增前端时不需要重复装配逻辑。
"""

from __future__ import annotations

import sys

from core.agent import Agent
from core.config import AppConfig, SearchConfig
from core.llm.base import LLMClient
from core.llm.fallback import FallbackLLMClient
from core.llm.openai_client import OpenAIChatClient
from core.mcp import McpConfigError, McpManager, load_mcp_config
from core.session import Session
from core.skills import SkillRegistry
from core.tools.builtin import build_default_registry
from core.tools.registry import ToolRegistry


def build_skill_registry(config: AppConfig) -> SkillRegistry:
    """扫描配置中的技能目录并装载技能。"""
    return SkillRegistry.from_directories(config.skills.dirs)


def build_registry(
    search_config: SearchConfig | None = None,
    skills: SkillRegistry | None = None,
    archive_dir: str | None = None,
    config: AppConfig | None = None,
) -> ToolRegistry:
    """构造默认工具注册表（参数统一来自 ``config``；缺省用默认值）。"""
    cli_config = config.cli if config else None
    fetch_config = config.fetch if config else None
    context = config.context if config else None
    return build_default_registry(
        search_config,
        skills,
        archive_dir,
        cli_config=cli_config,
        fetch_config=fetch_config,
        recall_limit=(context.recall_limit if context else None),
        snippet_max_chars=(context.snippet_max_chars if context else None),
    )


def attach_mcp(registry: ToolRegistry, config: AppConfig | None = None) -> McpManager:
    """读取 ``.mcp.json``（默认仅当前目录；可用 ``[mcp] files`` 指定额外配置）。"""
    manager = McpManager(
        default_timeout=(config.mcp.default_timeout if config else 60.0),
        connect_timeout=(config.mcp.connect_timeout if config else 30.0),
    )
    files = (config.mcp.files if config is not None else ())
    try:
        mcp_config = load_mcp_config(files=files)
    except McpConfigError as exc:
        print(f"[MCP] 配置错误: {exc}", file=sys.stderr)
        return manager
    if not mcp_config.servers:
        return manager
    manager.register(registry, mcp_config)
    return manager


async def attach_mcp_async(registry: ToolRegistry, config: AppConfig | None = None) -> McpManager:
    """异步加载 MCP：在后台线程连接各 Server 并注册工具，不阻塞前端事件循环。"""
    manager = McpManager(
        default_timeout=(config.mcp.default_timeout if config else 60.0),
        connect_timeout=(config.mcp.connect_timeout if config else 30.0),
    )
    files = (config.mcp.files if config is not None else ())
    try:
        mcp_config = load_mcp_config(files=files)
    except McpConfigError as exc:
        print(f"[MCP] 配置错误: {exc}", file=sys.stderr)
        return manager
    if mcp_config.servers:
        try:
            await manager.register_async(registry, mcp_config)
        except Exception as exc:  # noqa: BLE001 - MCP 加载失败不应阻塞启动
            print(f"[MCP] 加载失败: {exc}", file=sys.stderr)
    return manager


_GUARDRAILS = (
    "\n【回答纪律】每轮只能回答用户当前最新这一条消息，且必须与当前问题相关："
    "禁止复读/复述你上一轮已经给过的回答，禁止把上一句工具结果原文当成最终答案，"
    "禁止重复用户自己的话或历史对话里的旧内容。拿不出可靠答案时，就说明缺什么信息、"
    "需要用户补充什么，而不要用旧答案充数。"
)


def _apply_guardrails(prompt: str) -> str:
    """在系统提示词中追加模型无关的防复读规则。"""
    if not prompt:
        return _GUARDRAILS.lstrip("\n")
    return prompt.rstrip() + _GUARDRAILS


def build_llm(config: AppConfig) -> LLMClient:
    """装配 LLM 客户端；配置了 [llm_backup] 时返回主备自动切换的客户端。"""
    primary = OpenAIChatClient(config.llm)
    if config.llm_backup is None:
        return primary
    fallback = OpenAIChatClient(config.llm_backup)
    return FallbackLLMClient(primary=primary, fallback=fallback)


def build_agent(config: AppConfig, skills: SkillRegistry | None = None) -> Agent:
    """依据配置装配一个 Agent 实例。"""
    llm = build_llm(config)
    skill_registry = build_skill_registry(config) if skills is None else skills
    tools = build_registry(
        config.search, skill_registry, config.context.archive_dir, config=config
    )
    base_prompt = _apply_guardrails(config.agent.system_prompt)
    session = Session(system_prompt=skill_registry.render_prompt(base_prompt))

    def refresh_skills() -> None:
        skill_registry.reload()
        session.set_system_prompt(skill_registry.render_prompt(_apply_guardrails(config.agent.system_prompt)))

    agent = Agent(
        llm=llm,
        tools=tools,
        session=session,
        max_tool_rounds=config.agent.max_tool_rounds,
        before_turn=refresh_skills,
        context_config=config.context,
        agents_config=config.agents,
        empty_response_retries=config.agent.empty_response_retries,
    )
    # 会话首次加载时注入 AGENTS.md（一次注入、全程复用）
    if config.agents is not None and config.agents.inject:
        agent.inject_agents_md()
    return agent
