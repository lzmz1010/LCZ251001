"""End-to-end protocol tests: a real SDK client against the MCPServer.

The client and server talk the full JSON-RPC protocol over in-memory streams
(the same machinery the stdio transport uses), which exercises argument
handling, ``tools/list`` schema publishing and ``tools/call`` result shapes end
to end - without touching the real Go backend.

Each scenario runs inside a single task (the test's own) so anyio cancel
scopes are entered and exited in the same task.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.message import SessionMessage

from pet_hospital_mcp.server import LIST_PETS_TOOL_NAME, PetHospitalServer

from conftest import SAMPLE_DATA, ok_response

T = TypeVar("T")


async def _run_with_session(server: MCPServer, scenario: Callable[[ClientSession], Awaitable[T]]) -> T:
    client_send, server_recv = anyio.create_memory_object_stream[SessionMessage | Exception]()
    server_send, client_recv = anyio.create_memory_object_stream[SessionMessage]()

    lowlevel = server._lowlevel_server

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            lowlevel.run,
            server_recv,
            server_send,
            lowlevel.create_initialization_options(),
        )
        async with ClientSession(client_recv, client_send) as session:
            await session.initialize()
            return await scenario(session)


def _make_server(make_client) -> PetHospitalServer:
    client = make_client(lambda request: ok_response())
    return PetHospitalServer(client=client)


@pytest.mark.asyncio
async def test_round_trip_list_and_call(make_client) -> None:
    server = _make_server(make_client)

    async def scenario(session: ClientSession) -> None:
        tools = await session.list_tools()
        tool = next(t for t in tools.tools if t.name == LIST_PETS_TOOL_NAME)
        assert tool.title == "查询宠物档案"
        assert tool.description
        props = tool.input_schema["properties"]
        assert props["species"]["enum"] == ["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
        assert props["page"]["minimum"] == 1
        assert props["pageSize"]["maximum"] == 500

        result = await session.call_tool(LIST_PETS_TOOL_NAME, {"page": 1, "pageSize": 20, "species": "犬"})
        assert result.is_error is False
        assert result.structured_content == SAMPLE_DATA

    await _run_with_session(server, scenario)


@pytest.mark.asyncio
async def test_round_trip_validation_error(make_client) -> None:
    server = _make_server(make_client)

    async def scenario(session: ClientSession) -> None:
        result = await session.call_tool(LIST_PETS_TOOL_NAME, {"page": 0})
        assert result.is_error is True
        assert result.structured_content is not None
        assert result.structured_content["error"]["code"] == "VALIDATION_ERROR"
        assert "page" in result.structured_content["error"]["details"]

    await _run_with_session(server, scenario)


@pytest.mark.asyncio
async def test_round_trip_unknown_field_rejected(make_client) -> None:
    server = _make_server(make_client)

    async def scenario(session: ClientSession) -> None:
        result = await session.call_tool(LIST_PETS_TOOL_NAME, {"q": "豆豆", "unknown_field": 42})
        assert result.is_error is True
        assert result.structured_content is not None
        assert result.structured_content["error"]["code"] == "VALIDATION_ERROR"
        assert "unknown_field" in result.structured_content["error"]["details"]

    await _run_with_session(server, scenario)


@pytest.mark.asyncio
async def test_round_trip_returns_defaults_when_empty(make_client) -> None:
    server = _make_server(make_client)

    async def scenario(session: ClientSession) -> None:
        result = await session.call_tool(LIST_PETS_TOOL_NAME, {})
        assert result.is_error is False
        assert result.structured_content == SAMPLE_DATA

    await _run_with_session(server, scenario)