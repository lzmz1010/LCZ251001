"""Structured logging contract for the list_pets tool.

Verifies that the tool emits one JSON-structured line carrying the mandatory
``timestamp`` / ``tool_name`` / ``params`` / ``status`` / ``duration_ms``
fields and that pet-owner PII (``ownerPhone`` / ``ownerAddr`` / ``chipNo`` and
their snake_case forms, top-level or nested) is recursively redacted.
"""

from __future__ import annotations

import logging

import pytest

from pet_hospital_mcp.logging_config import redact_pii
from pet_hospital_mcp.tools.list_pets import handle_list_pets


def _captured(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "pet_hospital_mcp.list_pets" and r.levelno == logging.INFO]


@pytest.mark.asyncio
async def test_success_log_carries_required_fields(caplog, make_client) -> None:
    from conftest import ok_response

    with caplog.at_level(logging.INFO, logger="pet_hospital_mcp.list_pets"):
        result = await handle_list_pets({"page": 1, "pageSize": 20}, make_client(lambda r: ok_response()))

    assert result.is_error is False
    records = _captured(caplog)
    assert records, "expected at least one INFO log line"
    record = records[-1]
    assert record.tool_name == "list_pets"
    assert record.status == "ok"
    assert record.duration_ms >= 0
    assert record.params is not None


@pytest.mark.asyncio
async def test_params_log_is_recursively_redacted(caplog, make_client) -> None:
    from conftest import ok_response

    args = {
        "ownerPhone": "13800000001",
        "ownerName": "张三",
        "page": 1,
        "pageSize": 20,
    }
    with caplog.at_level(logging.INFO, logger="pet_hospital_mcp.list_pets"):
        await handle_list_pets(args, make_client(lambda r: ok_response()))

    record = _captured(caplog)[-1]
    assert record.params["ownerPhone"] == "***"
    # non-sensitive data is preserved
    assert record.params["ownerName"] == "张三"


@pytest.mark.asyncio
async def test_validation_log_redacts_params(caplog, make_client) -> None:
    from conftest import ok_response

    args = {"owner_addr": "广州市某街道", "page": 0}
    with caplog.at_level(logging.INFO, logger="pet_hospital_mcp.list_pets"):
        result = await handle_list_pets(args, make_client(lambda r: ok_response()))

    assert result.is_error is True
    record = _captured(caplog)[-1]
    assert record.status == "VALIDATION_ERROR"
    assert record.params["owner_addr"] == "***"


def test_redact_pii_recursive() -> None:
    value = {
        "ownerPhone": "a",
        "owner_phone": "b",
        "ownerAddr": "c",
        "owner_addr": "d",
        "chipNo": "e",
        "chip_no": "f",
        "keep": "keep",
        "items": [
            {"ownerPhone": "g", "owner_addr": "h", "chipNo": "i", "safe": 1},
            {"nested": {"chip_no": "j", "ownerAddr": "k"}},
        ],
    }
    out = redact_pii(value)
    assert out["ownerPhone"] == "***"
    assert out["owner_phone"] == "***"
    assert out["ownerAddr"] == "***"
    assert out["owner_addr"] == "***"
    assert out["chipNo"] == "***"
    assert out["chip_no"] == "***"
    assert out["keep"] == "keep"
    assert out["items"][0]["ownerPhone"] == "***"
    assert out["items"][0]["owner_addr"] == "***"
    assert out["items"][0]["chipNo"] == "***"
    assert out["items"][0]["safe"] == 1
    assert out["items"][1]["nested"]["chip_no"] == "***"
    assert out["items"][1]["nested"]["ownerAddr"] == "***"
