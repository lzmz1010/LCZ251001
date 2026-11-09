"""xAgent 核心层（core）。

本包只包含与界面无关的业务逻辑：

- ``config``    配置装载
- ``models``    领域模型（消息、工具调用）
- ``events``    对外事件（核心层唯一的前端输出通道）
- ``session``   会话上下文（历史记录）
- ``tools``     工具定义与注册表
- ``llm``       大模型客户端抽象与适配器
- ``agent``     Agent 主循环
- ``bootstrap`` 组合根：把各零件装配成一个可用的 Agent

core 不允许 import 任何 ``ui`` 包，保证业务逻辑可以脱离界面单独测试与复用。
"""

from core.agent import Agent
from core.bootstrap import build_agent, build_registry, build_skill_registry
from core.config import (
    AgentConfig,
    AppConfig,
    ContextConfig,
    LLMConfig,
    SearchConfig,
    SkillsConfig,
    load_config,
)
from core.errors import (
    AgentError,
    ConfigError,
    LLMError,
    ToolError,
    ToolNotFoundError,
)
from core.events import (
    AgentEvent,
    ErrorEvent,
    MessageCompleteEvent,
    StatusEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
    UserMessageEvent,
)
from core.models import Message, ToolCall
from core.session import Session
from core.skills import Skill, SkillRegistry

__all__ = [
    "Agent",
    "AgentConfig",
    "AgentError",
    "AgentEvent",
    "AppConfig",
    "ConfigError",
    "ContextConfig",
    "ErrorEvent",
    "LLMConfig",
    "LLMError",
    "Message",
    "MessageCompleteEvent",
    "SearchConfig",
    "Session",
    "Skill",
    "SkillRegistry",
    "SkillsConfig",
    "StatusEvent",
    "TextDeltaEvent",
    "ToolCall",
    "ToolCallEvent",
    "ToolError",
    "ToolNotFoundError",
    "ToolResultEvent",
    "TurnCompleteEvent",
    "UserMessageEvent",
    "build_agent",
    "build_registry",
    "build_skill_registry",
    "load_config",
]
