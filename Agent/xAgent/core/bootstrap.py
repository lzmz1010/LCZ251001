"""组合根：把 core 的各个零件装配成一个可直接使用的 Agent。

前端（TUI / Web / Desktop）只依赖这里产出的 ``Agent`` 对象，
新增前端时不需要重复装配逻辑。
"""

from __future__ import annotations

from core.agent import Agent
from core.config import AppConfig, SearchConfig
from core.llm.openai_client import OpenAIChatClient
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
) -> ToolRegistry:
    """构造默认工具注册表。"""
    return build_default_registry(search_config, skills)


def build_agent(config: AppConfig, skills: SkillRegistry | None = None) -> Agent:
    """依据配置装配一个 Agent 实例。"""
    llm = OpenAIChatClient(config.llm)
    skill_registry = build_skill_registry(config) if skills is None else skills
    tools = build_registry(config.search, skill_registry)
    base_prompt = config.agent.system_prompt
    session = Session(system_prompt=skill_registry.render_prompt(base_prompt))

    def refresh_skills() -> None:
        skill_registry.reload()
        session.set_system_prompt(skill_registry.render_prompt(base_prompt))

    return Agent(
        llm=llm,
        tools=tools,
        session=session,
        max_tool_rounds=config.agent.max_tool_rounds,
        before_turn=refresh_skills,
    )
