"""PetHospitalServer.call_tool behaviour at the server boundary."""

from __future__ import annotations

import json

import httpx
import pytest

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_TIMEOUT,
    VALIDATION_ERROR,
)
from pet_hospital_mcp.server import LIST_PETS_TOOL_NAME, PetHospitalServer
from pet_hospital_mcp.tools.list_pets import SCHEMA_PARAMS

from conftest import SAMPLE_DATA, ok_response


async def _build_server(make_client, handler) -> PetHospitalServer:
    return PetHospitalServer(client=make_client(handler))


@pytest.mark.asyncio
async def test_call_tool_returns_structured_data(make_client) -> None:
    server = await _build_server(make_client, lambda request: ok_response())
    result = await server.call_tool(LIST_PETS_TOOL_NAME, {"page": 1, "pageSize": 20})
    assert result.is_error is False
    assert result.structured_content == SAMPLE_DATA
    assert json.loads(result.content[0].text) == SAMPLE_DATA


@pytest.mark.asyncio
async def test_call_tool_applies_defaults(make_client) -> None:
    server = await _build_server(make_client, lambda request: ok_response())
    result = await server.call_tool(LIST_PETS_TOOL_NAME, {})
    assert result.is_error is False
    assert result.structured_content == SAMPLE_DATA


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"page": 0},
        {"species": "龙"},
        {"sortBy": "nope"},
        {"unknown_field": 1},
        {"min": 10, "max": 5},
        "not-a-dict",
    ],
)
async def test_call_tool_invalid_arguments_yield_unified_error(make_client, arguments) -> None:
    server = await _build_server(make_client, lambda request: ok_response())
    result = await server.call_tool(LIST_PETS_TOOL_NAME, arguments)
    assert result.is_error is True
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == VALIDATION_ERROR
    assert result.structured_content["error"]["message"]
    assert isinstance(result.structured_content["error"]["details"], dict)


@pytest.mark.asyncio
async def test_call_tool_backend_api_error_surfaces(make_client) -> None:
    server = await _build_server(make_client, lambda request: httpx.Response(500, text="boom"))
    result = await server.call_tool(LIST_PETS_TOOL_NAME, {})
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == BACKEND_API_ERROR
    assert result.structured_content["error"]["details"]["status_code"] == 500


@pytest.mark.asyncio
async def test_call_tool_backend_timeout_surfaces(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    server = await _build_server(make_client, handler)
    result = await server.call_tool(LIST_PETS_TOOL_NAME, {})
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == BACKEND_TIMEOUT


@pytest.mark.asyncio
async def test_unknown_tool_falls_back_to_sdk(make_client) -> None:
    server = await _build_server(make_client, lambda request: ok_response())
    with pytest.raises(Exception):
        await server.call_tool("no_such_tool", {})


@pytest.mark.asyncio
async def test_list_tools_advertises_list_pets_schema(make_client) -> None:
    server = await _build_server(make_client, lambda request: ok_response())
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert LIST_PETS_TOOL_NAME in names
    named = {tool.name: tool for tool in tools}[LIST_PETS_TOOL_NAME]
    props = named.input_schema["properties"]
    assert set(props) == {key for key, _ in SCHEMA_PARAMS}
    assert props["page"]["type"] == "integer"
    assert props["page"]["minimum"] == 1
    assert props["pageSize"]["maximum"] == 500
    assert props["species"]["enum"] == ["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
    assert props["status"]["enum"] == ["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
    assert len(props["sortBy"]["enum"]) == 11
    assert props["order"]["enum"] == ["asc", "desc"]


@pytest.mark.asyncio
async def test_health_route_is_registered(make_client) -> None:
    from pet_hospital_mcp.server import build_app

    server = await _build_server(make_client, lambda request: ok_response())
    app = build_app(server)
    paths = {getattr(route, "path", None): set(getattr(route, "methods", set()) or []) for route in app.routes}
    assert "/health" in paths
    assert "GET" in paths["/health"]