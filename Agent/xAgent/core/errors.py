"""核心层统一异常定义。"""

from __future__ import annotations


class AgentError(Exception):
    """所有 xAgent 异常的基类。"""


class ConfigError(AgentError):
    """配置缺失或非法。"""


class LLMError(AgentError):
    """调用大模型失败。"""


class ToolError(AgentError):
    """工具执行相关错误。"""


class ToolNotFoundError(ToolError):
    """请求调用了未注册的工具。"""
