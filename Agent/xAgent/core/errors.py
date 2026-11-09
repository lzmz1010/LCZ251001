"""核心层统一异常定义。"""

from __future__ import annotations


class AgentError(Exception):
    """所有 xAgent 异常的基类。"""


class ConfigError(AgentError):
    """配置缺失或非法。"""


class ConfigCreatedError(ConfigError):
    """配置文件原本缺失，已在当前目录自动生成示例配置。

    ``path``：新生成的配置文件路径；``message``：面向用户的提示文案。
    """

    def __init__(self, path, message):
        super().__init__(message)
        self.path = path
        self.message = message


class LLMError(AgentError):
    """调用大模型失败。"""


class ToolError(AgentError):
    """工具执行相关错误。"""


class ToolNotFoundError(ToolError):
    """请求调用了未注册的工具。"""
