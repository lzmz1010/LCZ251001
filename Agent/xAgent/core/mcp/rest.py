"""REST JSON API 适配。

当 ``.mcp.json`` 中的某个 Server 声明 ``transport: "rest"``（或 ``type: "rest"``）
时，用本模块把其 REST 端点包装成 xAgent 的 ``Tool``，让大模型能通过
Function Calling 直接调用这些 HTTP 接口（例如 PeiHospitalMCP 的 ``/api/v1/*``）。

工作方式：请求 ``GET {url}{discover}``（默认 ``/api/v1/endpoints``）拿到端点清单，
为每个 ``{Method, Path, Desc, Example}`` 条目生成一个工具：
- 路径占位符（``{id}``）→ 必填路径参数
- 示例 URL 中的查询参数 → 可选参数
- ``POST/PUT/PATCH`` 提供 ``body``（JSON 对象）参数

工具名由 HTTP 方法动作 + 路径片段拼接而成，冲突时加服务器前缀。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx

from core.errors import ToolError
from core.mcp.config import McpConfig, McpServerConfig
from core.mcp.manager import _slug
from core.tools.base import Tool, ToolParameter
from core.tools.registry import ToolRegistry

DEFAULT_TIMEOUT = 30.0

_PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")

_BODY_METHODS = {"POST", "PUT", "PATCH"}
_BASE_SEGMENTS = {"api", "v1", "api/v1"}


class RestError(ToolError):
    """连接或调用 REST API 失败。"""


@dataclass(frozen=True)
class RestEndpoint:
    """单个 REST 端点。"""

    method: str
    path: str
    description: str = ""
    example: str = ""


def _assign_used_name(
    server_name: str, preferred: str, used_names: set[str]
) -> str:
    """返回一个不与现有名称冲突的名字；冲突时加服务器前缀。"""
    candidate = preferred
    if candidate in used_names:
        candidate = f"{_slug(server_name)}_{preferred}"
    counter = 1
    while candidate in used_names:
        candidate = f"{_slug(server_name)}_{preferred}_{counter}"
        counter += 1
    return candidate


class RestClient:
    """读取 REST 端点清单的客户端。"""

    def __init__(self, server: McpServerConfig) -> None:
        self._server = server
        self._timeout = server.timeout or DEFAULT_TIMEOUT

    @property
    def server_name(self) -> str:
        return self._server.name

    @property
    def base_url(self) -> str:
        return self._server.url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        return self._server.headers

    @property
    def timeout(self) -> float:
        return self._timeout

    def discover(self) -> list[RestEndpoint]:
        """拉取端点清单（``GET {base}{discover}``）并解析。"""
        url = f"{self.base_url}{self._server.discover}"
        data = self._request_json("GET", url)
        return self._extract(data)

    @staticmethod
    def _extract(data: Any) -> list[RestEndpoint]:
        if isinstance(data, dict):
            data = data.get("data", data)
        if isinstance(data, dict):
            data = data.get("endpoints", [])
        if not isinstance(data, list):
            return []
        endpoints: list[RestEndpoint] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            method = str(entry.get("Method") or entry.get("method") or "").upper()
            path = str(entry.get("Path") or entry.get("path") or "")
            if not method or not path:
                continue
            endpoints.append(
                RestEndpoint(
                    method=method,
                    path=path,
                    description=str(entry.get("Desc") or entry.get("description") or ""),
                    example=str(entry.get("Example") or entry.get("example") or ""),
                )
            )
        return endpoints

    def _request_json(self, method: str, url: str, payload: Any = None) -> Any:
        try:
            with httpx.Client(headers=self.headers, timeout=self._timeout) as client:
                if method in _BODY_METHODS and payload is not None:
                    response = client.request(method, url, json=payload)
                else:
                    response = client.request(method, url)
        except httpx.HTTPError as exc:
            raise RestError(f"请求 {method} {url} 失败: {exc}") from exc
        try:
            return response.json()
        except ValueError:
            return response.text


def _action_for(method: str, path: str) -> str:
    """根据 HTTP 方法与是否存在路径占位符推断动词。"""
    has_placeholder = "{" in path
    method = method.upper()
    if method == "GET":
        return "get" if has_placeholder else "list"
    if method == "POST":
        return "add" if has_placeholder else "create"
    if method == "PUT":
        return "update"
    if method == "PATCH":
        return "patch"
    if method == "DELETE":
        return "delete"
    return method.lower()


def _resource_name(path: str) -> str:
    """去掉基路径与占位符，得到资源名。"""
    segments = [
        seg
        for seg in path.split("/")
        if seg and seg.lower() not in _BASE_SEGMENTS and "{" not in seg
    ]
    return "_".join(segments) or "root"


def make_tool_name(method: str, path: str) -> str:
    """由方法+路径生成一个可读且稳定的工具名。"""
    action = _action_for(method, path)
    resource = _resource_name(path)
    return f"{action}_{resource}"


def _query_from_example(example: str) -> dict[str, str]:
    """从示例 URL 中提取查询参数键值。"""
    match = re.search(r"[?]([^\"'\s]+)", example)
    if not match:
        return {}
    parsed = parse_qs(match.group(1))
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _infer_type(value: str) -> str:
    stripped = value.strip()
    if re.fullmatch(r"-?\d+", stripped):
        return "integer"
    if re.fullmatch(r"-?\d+\.\d+", stripped):
        return "number"
    return "string"


def build_rest_parameters(endpoint: RestEndpoint) -> tuple[ToolParameter, ...]:
    """把一个 REST 端点转成工具参数。"""
    parameters: list[ToolParameter] = []
    for param_name in re.findall(r"\{([^}]+)\}", endpoint.path):
        parameters.append(
            ToolParameter(
                name=param_name,
                type="string",
                description=f"路径参数 {param_name}",
                required=True,
            )
        )
    for key, value in _query_from_example(endpoint.example).items():
        parameters.append(
            ToolParameter(
                name=key,
                type=_infer_type(value),
                description=f"查询参数 {key}={value}（示例值）",
                required=False,
            )
        )
    if endpoint.method.upper() in _BODY_METHODS:
        parameters.append(
            ToolParameter(
                name="body",
                type="object",
                description="请求体 JSON 对象；字段可参考示例描述",
                required=False,
            )
        )
    return tuple(parameters)


class RestTool(Tool):
    """把 REST 端点包装成本地 ``Tool``。"""

    name: str = ""
    description: str = ""
    parameters: tuple[ToolParameter, ...] = ()

    def __init__(
        self,
        client: RestClient,
        *,
        name: str,
        method: str,
        path: str,
        description: str,
        parameters: tuple[ToolParameter, ...],
    ) -> None:
        self.name = name
        self.method = method
        self.path = path
        self.description = description
        self.parameters = parameters
        self._client = client

    @property
    def server_name(self) -> str:
        return self._client.server_name

    def invoke(self, **kwargs: Any) -> str:
        """执行 HTTP 请求，返回格式化后的结果。"""
        path_params: dict[str, str] = {}
        query: dict[str, Any] = {}
        body: Any = None
        for key, value in kwargs.items():
            if key == "body":
                body = value
            elif "{" + key + "}" in self.path:
                path_params[key] = str(value)
            else:
                query[key] = value

        path = self.path
        for key, value in path_params.items():
            path = path.replace("{" + key + "}", value)
        url = f"{self._client.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"

        payload = body if self.method.upper() in _BODY_METHODS and body is not None else None
        try:
            with httpx.Client(
                headers=self._client.headers, timeout=self._client.timeout
            ) as client:
                response = client.request(self.method, url, json=payload)
        except httpx.HTTPError as exc:
            raise ToolError(f"[REST] 请求 {self.method} {url} 失败: {exc}") from exc
        return self._format_response(response)

    @staticmethod
    def _format_response(response: httpx.Response) -> str:
        try:
            data: Any = response.json()
        except ValueError:
            data = response.text
        body_text = (
            json.dumps(data, ensure_ascii=False, indent=2, default=str)
            if isinstance(data, (dict, list))
            else str(data)
        )
        ok = 200 <= response.status_code < 300
        if not ok:
            raise ToolError(
                f"[REST 错误] HTTP {response.status_code} {response.text}\n\n{body_text}"
            )
        return f"HTTP {response.status_code}\n\n{body_text}"


class RestManager:
    """连接 REST Server、发现端点并注册进工具注册表。"""

    def __init__(self) -> None:
        self._mapping: dict[str, tuple[str, str]] = {}
        self._errors: list[str] = []

    @property
    def mapping(self) -> dict[str, tuple[str, str]]:
        return dict(self._mapping)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def register(self, registry: ToolRegistry, config: McpConfig) -> None:
        used_names: set[str] = set(registry.names)
        for server in config.servers:
            try:
                client = RestClient(server)
                endpoints = client.discover()
            except Exception as exc:  # noqa: BLE001 - 单服务器失败不影响其他
                message = (
                    f"无法接入 REST Server '{server.name}' ({server.url}): {exc}"
                )
                self._errors.append(message)
                print(f"[MCP] {message}", file=sys.stderr)
                continue
            for endpoint in endpoints:
                preferred = make_tool_name(endpoint.method, endpoint.path)
                exposed = _assign_used_name(server.name, preferred, used_names)
                used_names.add(exposed)
                self._mapping[exposed] = (server.name, endpoint.method)
                description = endpoint.description or endpoint.path
                if endpoint.example:
                    description = f"{description}\n示例: {endpoint.example}"
                registry.register(
                    RestTool(
                        client,
                        name=exposed,
                        method=endpoint.method,
                        path=endpoint.path,
                        description=description,
                        parameters=build_rest_parameters(endpoint),
                    )
                )
                print(
                    f"[MCP] 已接入 REST 工具: '{server.name}'::{endpoint.method} "
                    f"{endpoint.path} (暴露名 '{exposed}')",
                    file=sys.stderr,
                )
