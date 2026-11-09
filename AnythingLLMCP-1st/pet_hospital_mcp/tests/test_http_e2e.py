"""HTTP-level stateless end-to-end verification.

Runs the real ASGI app with uvicorn on an ephemeral local port and talks to it
over genuine stateless Streamable HTTP, exercising:

* the ``/health`` endpoint,
* the modern ``server/discover`` negotiation (protocol ``2026-07-28``) rather
  than the legacy ``initialize`` handshake,
* ``tools/list`` discovery and ``tools/call`` invocation of ``list_pets``,
* no ``Mcp-Session-Id`` / stateful resumption being required.

The Go backend is never contacted - it is simulated with ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn

from pet_hospital_mcp.server import build_app

from conftest import ok_response


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def http_mcp_server(make_client) -> tuple[str, uvicorn.Server]:
    """Start the app on an ephemeral port in a background thread."""
    client = make_client(lambda request: ok_response())
    app = build_app(client=client)

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.005)
    try:
        yield f"http://127.0.0.1:{port}", server
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_health_via_http(http_mcp_server) -> None:
    base_url, _ = http_mcp_server
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{base_url}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "pet-hospital-mcp"


@pytest.mark.asyncio
async def test_stateless_discover_call_over_http(http_mcp_server) -> None:
    base_url, _ = http_mcp_server
    from httpx2 import AsyncClient as H2Client
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(base_url + "/mcp", http_client=H2Client(timeout=15)) as (read, write):
        async with ClientSession(read, write) as session:
            discover = await session.discover()
            assert "2026-07-28" in discover.supported_versions

            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            assert "list_pets" in names

            result = await session.call_tool("list_pets", {"page": 1, "pageSize": 20, "species": "犬"})
            assert result.is_error is False
            assert result.structured_content["page"] == 1
            assert result.structured_content["pageSize"] == 20
            assert isinstance(result.structured_content["items"], list)


@pytest.mark.asyncio
async def test_stateless_call_requires_no_session_id(http_mcp_server) -> None:
    base_url, _ = http_mcp_server
    async with httpx.AsyncClient() as client:
        # a self-contained POST to /mcp must succeed without any session id
        response = await client.post(
            f"{base_url}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert response.status_code == 200
    assert "Mcp-Session-Id" not in response.headers
    # Streamable HTTP answers with SSE; the JSON-RPC result lives in `data:`.
    data_line = next(line for line in response.text.splitlines() if line.startswith("data:"))
    payload: dict[str, Any] = json.loads(data_line[5:].strip())
    assert "error" not in payload
    assert "result" in payload
