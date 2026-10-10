"""RestClient behaviour: request building, retries and error classification."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    BackendApiError,
    BackendInvalidResponseError,
    BackendTimeoutError,
    BackendUnavailableError,
)
from pet_hospital_mcp.rest_client import RestClient

from conftest import SAMPLE_DATA, ok_response


@pytest.mark.asyncio
async def test_list_pets_success_builds_query_and_returns_data(make_client) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return ok_response()

    client = make_client(handler)
    data = await client.list_pets(
        {"q": "豆豆", "species": "犬", "status": "待就诊", "page": 2, "pageSize": 50, "sortBy": "totalCost", "order": "desc", "min": 10, "max": 500.5}
    )
    assert data == SAMPLE_DATA
    assert captured["method"] == "GET"
    assert "api/v1/pets" in captured["url"]
    for expected in ["q=%E8%B1%86%E8%B1%86", "species=%E7%8A%AC", "page=2", "pageSize=50", "sortBy=totalCost", "order=desc", "min=10", "max=500.5"]:
        assert expected in captured["url"]


@pytest.mark.asyncio
async def test_list_pets_drops_none_values(make_client) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return ok_response()

    client = make_client(handler)
    await client.list_pets({"q": None, "name": "豆豆", "page": 1, "pageSize": 20, "min": None})
    assert "q=" not in captured["url"]
    assert "min=" not in captured["url"]
    assert "name=%E8%B1%86%E8%B1%86" in captured["url"]


@pytest.mark.asyncio
async def test_http_500_maps_to_api_error(make_client) -> None:
    client = make_client(lambda request: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(BackendApiError) as excinfo:
        await client.list_pets({})
    assert excinfo.value.to_envelope()["error"]["code"] == BACKEND_API_ERROR
    assert excinfo.value.to_envelope()["error"]["details"]["status_code"] == 500


@pytest.mark.asyncio
async def test_body_code_not_200_maps_to_api_error(make_client) -> None:
    client = make_client(lambda request: httpx.Response(200, json={"code": 500, "message": "server broke", "data": None}))
    with pytest.raises(BackendApiError) as excinfo:
        await client.list_pets({})
    envelope = excinfo.value.to_envelope()
    assert envelope["error"]["code"] == BACKEND_API_ERROR
    assert envelope["error"]["details"]["code"] == 500


@pytest.mark.asyncio
async def test_non_json_body_maps_to_invalid_response(make_client) -> None:
    client = make_client(lambda request: httpx.Response(200, content=b"<html>oops</html>"))
    with pytest.raises(BackendInvalidResponseError) as excinfo:
        await client.list_pets({})
    assert excinfo.value.to_envelope()["error"]["code"] == BACKEND_INVALID_RESPONSE


@pytest.mark.asyncio
async def test_missing_data_maps_to_invalid_response(make_client) -> None:
    client = make_client(lambda request: httpx.Response(200, json={"code": 200, "message": "ok"}))
    with pytest.raises(BackendInvalidResponseError) as excinfo:
        await client.list_pets({})
    assert excinfo.value.to_envelope()["error"]["code"] == BACKEND_INVALID_RESPONSE


@pytest.mark.asyncio
async def test_data_not_object_maps_to_invalid_response(make_client) -> None:
    client = make_client(lambda request: httpx.Response(200, json={"code": 200, "message": "ok", "data": [1, 2]}))
    with pytest.raises(BackendInvalidResponseError) as excinfo:
        await client.list_pets({})
    assert excinfo.value.to_envelope()["error"]["code"] == BACKEND_INVALID_RESPONSE


@pytest.mark.asyncio
async def test_connect_failure_maps_to_unavailable_after_retries(make_client) -> None:
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append("x")
        raise httpx.ConnectError(f"connection refused for {request.url}")

    client = make_client(handler, retries=2)
    with pytest.raises(BackendUnavailableError) as excinfo:
        await client.list_pets({})
    assert len(attempts) == client.attempts_allowed == 3
    assert excinfo.value.to_envelope()["error"]["code"] == BACKEND_UNAVAILABLE
    assert excinfo.value.to_envelope()["error"]["details"]["attempts"] == 3


@pytest.mark.asyncio
async def test_timeout_maps_to_timeout_after_retries(make_client) -> None:
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append("x")
        raise httpx.ReadTimeout("read timed out")

    client = make_client(handler, retries=1)
    with pytest.raises(BackendTimeoutError) as excinfo:
        await client.list_pets({})
    assert len(attempts) == 2
    assert excinfo.value.to_envelope()["error"]["code"] == BACKEND_TIMEOUT


@pytest.mark.asyncio
async def test_transient_failure_then_success_is_retried(make_client) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("first attempt fails")
        return ok_response()

    client = make_client(handler, retries=2)
    data = await client.list_pets({})
    assert data == SAMPLE_DATA
    assert calls == 2


@pytest.mark.asyncio
async def test_http_error_message_includes_status_code(make_client) -> None:
    client = make_client(lambda request: httpx.Response(503, text="unavailable"))
    with pytest.raises(BackendApiError) as excinfo:
        await client.list_pets({})
    assert "503" in excinfo.value.message