"""Strict validation matrix for the list_pets tool arguments."""

from __future__ import annotations

import math
from typing import Any

import pytest

from pet_hospital_mcp.errors import VALIDATION_ERROR
from pet_hospital_mcp.tools.list_pets import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    ORDERS,
    SORT_FIELDS,
    SPECIES,
    STATUSES,
    ListPetsParams,
    validate_arguments,
)


def _error_code(raw: Any) -> str | None:
    _, envelope = validate_arguments(raw)
    if envelope is None:
        return None
    return envelope["error"]["code"]


INVALID_CASES: list[tuple[str, dict[str, Any]]] = [
    ("species 不在后端枚举中", {"species": "龙"}),
    ("status 不在后端枚举中", {"status": "已死亡"}),
    ("sortBy 不在后端枚举中", {"sortBy": "price"}),
    ("order 非法", {"order": "up"}),
    ("page=0", {"page": 0}),
    ("page 为负数", {"page": -3}),
    ("pageSize=0", {"pageSize": 0}),
    ("pageSize 超过 500", {"pageSize": 501}),
    ("min 为负数", {"min": -5}),
    ("max 为负数", {"max": -1.5}),
    ("min 大于 max", {"min": 100, "max": 50}),
    ("min 为 NaN", {"min": float("nan")}),
    ("max 为 Infinity", {"max": float("inf")}),
    ("page 类型错误（字符串）", {"page": "abc"}),
    ("pageSize 类型错误（小数）", {"pageSize": 2.5}),
    ("species 类型错误（数字）", {"species": 123}),
    ("q 类型错误（数字）", {"q": 456}),
    ("min 类型错误（字符串）", {"min": "十"}),
    ("未知字段", {"bogus_field": 1}),
    ("多个未知字段", {"foo": 1, "bar": 2}),
    ("非对象参数", 42),
    ("参数为空串枚举", {"species": ""}),
]

VALID_CASES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    ("空参数使用默认分页", {}, {"page": 1, "pageSize": 20}),
    (
        "全参数合法",
        {
            "q": "豆豆",
            "name": "豆豆",
            "ownerName": "张三",
            "ownerPhone": "13800000001",
            "species": "犬",
            "doctor": "陈医生",
            "disease": "感冒",
            "status": "待就诊",
            "min": 0,
            "max": 500.5,
            "sortBy": "totalCost",
            "order": "desc",
            "page": 2,
            "pageSize": 50,
        },
        {"page": 2, "pageSize": 50, "min": 0, "max": 500.5},
    ),
    ("只传 min 无 max 合法", {"min": 10}, {}),
    ("只传 max 无 min 合法", {"max": 10}, {}),
    ("min 等于 max 合法", {"min": 5.0, "max": 5.0}, {}),
    ("整数型数字参数", {"page": 1, "pageSize": 500, "min": 3, "max": 4}, {}),
    ("物种边界值", {"species": "其他"}, {}),
    ("状态边界值", {"status": "慢性病随访"}, {}),
]


@pytest.mark.parametrize("label,raw", INVALID_CASES, ids=[c[0] for c in INVALID_CASES])
def test_validation_rejects_invalid(label: str, raw: dict[str, Any]) -> None:
    params, envelope = validate_arguments(raw)
    assert params is None
    assert envelope is not None
    assert envelope["error"]["code"] == VALIDATION_ERROR
    assert envelope["error"]["message"]
    assert "details" in envelope["error"]
    assert envelope["error"]["details"]


@pytest.mark.parametrize("label,raw,expected", VALID_CASES, ids=[c[0] for c in VALID_CASES])
def test_validation_accepts_valid(label: str, raw: dict[str, Any], expected: dict[str, Any]) -> None:
    params, envelope = validate_arguments(raw)
    assert envelope is None
    assert params is not None
    assert isinstance(params, ListPetsParams)


def test_defaults_are_applied() -> None:
    params, envelope = validate_arguments({})
    assert envelope is None
    assert params is not None
    assert params.page == DEFAULT_PAGE
    assert params.pageSize == DEFAULT_PAGE_SIZE
    assert params.species is None


def test_model_dump_drops_none_filters() -> None:
    params, _ = validate_arguments({"q": "豆豆", "page": 1, "pageSize": 20})
    assert params is not None
    payload = params.model_dump(exclude_none=True, mode="json")
    assert payload == {"q": "豆豆", "page": 1, "pageSize": 20}


def test_known_enums_match_backend_constants() -> None:
    assert SPECIES == ("犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他")
    assert STATUSES == ("待就诊", "就诊中", "住院中", "已康复", "慢性病随访")
    assert "other" not in SORT_FIELDS and "totalCost" in SORT_FIELDS
    assert ORDERS == ("asc", "desc")