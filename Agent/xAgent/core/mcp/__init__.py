"""MCP 客户端集成。

职责：读取 ``.mcp.json`` 配置，连接 Streamable HTTP 的 MCP Server，
将其提供的工具以 ``Tool`` 的形式注册进 xAgent 的工具注册表，
使大模型能像调用本地工具一样调用 MCP 工具。
"""

from core.mcp.config import (
    resolve_mcp_files,
    McpConfig,
    McpConfigError,
    McpServerConfig,
    find_mcp_config,
    load_mcp_config,
)
from core.mcp.client import McpClient, McpClientError
from core.mcp.manager import McpManager
from core.mcp.tool import McpTool, build_parameters

__all__ = [
    "McpClient",
    "McpClientError",
    "McpConfig",
    "McpConfigError",
    "McpManager",
    "resolve_mcp_files",
    "McpServerConfig",
    "McpTool",
    "build_parameters",
    "find_mcp_config",
    "load_mcp_config",
]
