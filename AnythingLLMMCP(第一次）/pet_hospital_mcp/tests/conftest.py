"""Shared fixtures for the pet hospital MCP tests.

The tests never touch the real Go backend: every HTTP interaction is simulated
with ``httpx.MockTransport`` handlers.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx # noqa: F401
import pytest

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import RestClient

HANDLER = Callable[[httpx.Request], httpx.Response]

SAMPLE_DATA: dict[str, Any] = {
    "items": [
        {
            "id": "PET-000001",
            "name": "豆豆",
            "species": "犬",
            "breed": "柴犬",
            "gender": "公",
            "ageMonths": 24,
            "color": "棕色",
            "ownerName": "张三",
            "ownerPhone": "13800000001",
            "doctor": "陈医生",
            "disease": "感冒",
            "status": "待就诊",
            "totalCost": 123.45,
            "visitCount": 3,
            "createdAt": "2026-09-15T13:50:11+08:00",
            "updatedAt": "2026-09-15T13:50:11+08:00",
            "records": None,
            "charges": None,
        }
    ],
    "total": 1,
    "page": 1,
    "pageSize": 20,
    "totalPages": 1,
    "totalCost": 123.45,
}


def ok_response(data: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"code": 200, "message": "ok", "data": data if data is not None else SAMPLE_DATA, "time": "2026-09-24T00:00:00+08:00"},
    )


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env({"PET_HOSPITAL_BASE_URL": "http://pet-backend.test"})


@pytest.fixture
def make_client() -> Callable[..., RestClient]:
    """Factory producing a RestClient bound to a MockTransport handler."""

    def _make(handler: HANDLER, *, retries: int = 0, timeout: float = 1.0) -> RestClient:
        return RestClient(
            "http://pet-backend.test",
            timeout_seconds=timeout,
            retries=retries,
            transport=httpx.MockTransport(handler),
        )

    return _make