"""``.mcp.json`` 配置解析。

MCP Server 连接信息存放在运行 Agent 所在“当前项目”目录下的
``.mcp.json`` 文件中（不是 xAgent 自己源代码所在的目录）。

支持标准的 MCP 客户端配置格式：:

    {
      "mcpServers": {
        "serverName": {
          "url": "http://127.0.0.1:8080/",
          "headers": {"Authorization": "Bearer xxx"},
          "timeout": 30
        }
      }
    }

本实现仅支持基于 URL 的 Streamable HTTP 协议；使用 ``command``/``args``
启动本地子进程的 stdio Server 不在支持范围内，将被跳过并给出提示。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core.config import PROJECT_ROOT


class McpConfigError(Exception):
    """``.mcp.json`` 配置缺失或非法。"""


@dataclass(frozen=True)
class McpServerConfig:
    """单个远程 Server 的连接信息。

    ``transport`` 取值 ``"mcp"``（默认，Streamable HTTP 协议）或 ``"rest"``
    （对 REST JSON API 做适配，把端点包装成工具）。``discover`` 仅 REST 场景
    使用，指向列出所有端点的接口。
    """

    name: str
    url: str
    transport: str = "mcp"
    discover: str = "/api/v1/endpoints"
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float | None = None

    @property
    def is_rest(self) -> bool:
        return self.transport == "rest"


@dataclass(frozen=True)
class McpConfig:
    """全部 MCP Server 的配置。"""

    servers: tuple[McpServerConfig, ...] = ()


def find_mcp_config() -> Path | None:
    """寻找 ``.mcp.json``：默认只检查「启动时当前目录」。"""
    candidate = Path.cwd() / ".mcp.json"
    if candidate.is_file():
        return candidate
    return None


def resolve_mcp_files(files: Iterable[str | os.PathLike[str]]) -> list[Path]:
    """把显式配置路径解析为绝对路径列表（相对当前目录解析，去重）。"""
    paths: list[Path] = []
    seen: set[str] = set()
    for raw in files:
        raw = str(raw or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        resolved = candidate.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        paths.append(resolved)
    return paths


def _parse_server(name: str, raw: dict[str, Any]) -> McpServerConfig | None:
    """解析一个 server 条目；仅支持基于 URL 的 Streamable HTTP。"""
    if not isinstance(raw, dict):
        raise McpConfigError(f"server '{name}' 配置必须是 JSON 对象")

    url = str(raw.get("url", "")).strip()
    if not url:
        if raw.get("command"):
            raise McpConfigError(
                f"server '{name}' 使用 stdio 启动（command），当前仅支持 "
                "Streamable HTTP（需要 url 字段）"
            )
        raise McpConfigError(f"server '{name}' 缺少 url 字段")

    transport = str(raw.get("transport") or raw.get("type") or "mcp").strip().lower()
    transport = transport if transport in ("mcp", "rest") else "mcp"

    headers = {
        str(k): str(v)
        for k, v in (raw.get("headers") or {}).items()
        if isinstance(v, str)
    }
    timeout = raw.get("timeout")
    timeout_f: float | None = None
    if timeout is not None:
        try:
            timeout_f = float(timeout)
        except (TypeError, ValueError) as exc:
            raise McpConfigError(
                f"server '{name}' 的 timeout 不是合法数字: {timeout}"
            ) from exc

    return McpServerConfig(
        name=str(name),
        url=url,
        transport=transport,
        discover=str(raw.get("discover") or "/api/v1/endpoints"),
        headers=headers,
        timeout=timeout_f,
    )


def _read_mcp_file(path: Path) -> dict[str, McpServerConfig]:
    """读取单个 ``.mcp.json`` 文件，返回 名称 → 服务器 的映射。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"MCP 配置文件解析失败: {path}: {exc}") from exc
    except OSError as exc:
        raise McpConfigError(f"读取 MCP 配置文件失败: {path}: {exc}") from exc

    raw_servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not raw_servers:
        raise McpConfigError(f"MCP 配置文件 {path} 缺少 'mcpServers' 字段")
    if not isinstance(raw_servers, dict):
        raise McpConfigError(f"MCP 配置文件 {path} 的 'mcpServers' 必须是对象")

    return {name: _parse_server(name, raw) for name, raw in raw_servers.items()}


def load_mcp_config(
    path: str | Path | None = None,
    files: Iterable[str | os.PathLike[str]] = (),
) -> McpConfig:
    """读取 ``.mcp.json`` 并返回配置对象。文件不存在时返回空配置。

    :param path: 显式指定单个配置文件（优先级最高）。
    :param files: 显式指定多个配置文件；非空时按顺序合并（同名服务器后者覆盖）。
    :return: 合并后的服务器配置；无任何配置文件时返回空配置。
    """
    if path is not None:
        config_path = Path(path)
        if not config_path.is_file():
            raise McpConfigError(f"MCP 配置文件不存在: {config_path}")
        return McpConfig(servers=tuple(_read_mcp_file(config_path).values()))

    paths: list[Path] = []
    if files:
        paths = resolve_mcp_files(files)
    else:
        default = find_mcp_config()
        if default is not None:
            paths = [default]
    if not paths:
        return McpConfig()

    merged: dict[str, McpServerConfig] = {}
    for config_path in paths:
        if not config_path.is_file():
            continue
        merged.update(_read_mcp_file(config_path))
    return McpConfig(servers=tuple(merged.values()))
