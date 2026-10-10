"""MCP server assembly for the pet hospital service.

:class:`PetHospitalServer` is an :class:`mcp.server.mcpserver.MCPServer` subclass.
It overrides :meth:`MCPServer.call_tool` so ``list_pets`` arguments are
validated against the raw request dict (returning the unified error envelope
when they fail) before any backend call is made, while still surfacing the
tool in ``tools/list`` with a hand-built input schema.
"""

from __future__ import annotations

import typing
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import WithJsonSchema
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .config import Settings
from .rest_client import RestClient
from .tools.list_pets import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    SCHEMA_PARAMS,
    TOOL_DESCRIPTION,
    handle_list_pets,
)

LIST_PETS_TOOL_NAME = "list_pets"

_SERVER_NAME = "pet-hospital-mcp"
_SERVER_TITLE = "宠物医院 MCP 服务"
_SERVER_DESCRIPTION = "面向宠物医院管理系统的 MCP 服务（阶段一：宠物档案查询）"
_SERVER_INSTRUCTIONS = (
    "本服务为无状态 Streamable HTTP MCP 服务，仅提供 list_pets 一个工具，"
    "用于查询宠物医院管理系统的宠物档案列表。"
    "所有参数都会在后端调用的边界处进行严格校验，校验失败与后端错误均返回统一错误结构。"
)


class PetHospitalServer(MCPServer):
    """MCPServer that validates and dispatches ``list_pets`` calls itself."""

    def __init__(self, settings: Settings | None = None, client: RestClient | None = None) -> None:
        self._conf = settings or Settings.from_env()
        self._client = client or RestClient(
            self._conf.pet_hospital_base_url,
            self._conf.pet_hospital_timeout,
            self._conf.pet_hospital_retries,
        )

        super().__init__(
            name=_SERVER_NAME,
            title=_SERVER_TITLE,
            description=_SERVER_DESCRIPTION,
            instructions=_SERVER_INSTRUCTIONS,
            version=__version__,
            log_level=self._conf.log_level,
        )

        self._register_tool()
        self._register_health_route()

    @property
    def rest_client(self) -> RestClient:
        return self._client

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any = None,
    ) -> CallToolResult:
        """Intercept ``list_pets`` so raw arguments drive validation.

        The SDK's generated argument model silently drops unknown fields and
        coerces types, so ``list_pets`` is validated here against the raw dict
        before anything else runs. Every outcome is a ``CallToolResult``.
        """
        if name == LIST_PETS_TOOL_NAME:
            return await handle_list_pets(arguments, self._client)
        return await super().call_tool(name, arguments, context)

    def _register_tool(self) -> None:
        self.add_tool(
            _list_pets_stub,
            name=LIST_PETS_TOOL_NAME,
            title="查询宠物档案",
            description=TOOL_DESCRIPTION,
            structured_output=False,
        )

    def _register_health_route(self) -> None:
        @self.custom_route("/health", methods=["GET"])
        async def _health(_request: Request) -> JSONResponse:
            return JSONResponse(
                {
                    "status": "ok",
                    "service": _SERVER_NAME,
                    "version": __version__,
                    "backend_base_url": self._conf.pet_hospital_base_url,
                }
            )


async def _list_pets_stub(
    q: Any = None,
    name: Any = None,
    ownerName: Any = None,
    ownerPhone: Any = None,
    species: Any = None,
    doctor: Any = None,
    disease: Any = None,
    status: Any = None,
    min: Any = None,
    max: Any = None,
    sortBy: Any = None,
    order: Any = None,
    page: Any = DEFAULT_PAGE,
    pageSize: Any = DEFAULT_PAGE_SIZE,
) -> CallToolResult:
    """Never invoked: PetHospitalServer.call_tool short-circuits list_pets.

    Registered so tools/list advertises the correct input schema; the
    annotations below are replaced with per-parameter JSON-schema hints.
    """
    raise AssertionError("list_pets must be dispatched through PetHospitalServer.call_tool")


_list_pets_stub.__annotations__ = {
    **_list_pets_stub.__annotations__,
    **{key: typing.Annotated[Any, WithJsonSchema(schema)] for key, schema in SCHEMA_PARAMS},
}


def create_server(
    settings: Settings | None = None,
    client: RestClient | None = None,
) -> PetHospitalServer:
    """Build a ready-to-run :class:`PetHospitalServer`."""
    return PetHospitalServer(settings=settings, client=client)


def build_app(
    server: PetHospitalServer | None = None,
    settings: Settings | None = None,
    client: RestClient | None = None,
) -> Starlette:
    """Return the Stateless Streamable HTTP Starlette app for the MCP server."""
    server = server or create_server(settings=settings, client=client)
    return server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True)