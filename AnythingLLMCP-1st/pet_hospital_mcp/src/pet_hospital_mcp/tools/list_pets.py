"""The ``list_pets`` tool.

* Strict :class:`ListPetsParams` Pydantic validation of the raw tool arguments
  (rejects unknown fields, ``NaN``/``Infinity``, wrong types, out-of-range or
  cross-field-inconsistent values, and enum members not present in the real Go
  backend).
* A unified structured error envelope (``{"error": {"code", "message",
  "details"}}``) delivered as ``CallToolResult(is_error=True)``.
* On success the structured result mirrors the Go backend ``data`` object
  (``items`` / ``total`` / ``page`` / ``pageSize`` / ``totalPages`` /
  ``totalCost``).
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Literal

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..errors import (
    BackendError,
    INTERNAL_ERROR,
    error_envelope,
    validation_error,
)
from ..rest_client import RestClient

logger = logging.getLogger("pet_hospital_mcp.list_pets")

# Allowed values are taken verbatim from the live Go backend (GET /api/v1/meta).
SPECIES: tuple[str, ...] = ("犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他")
STATUSES: tuple[str, ...] = ("待就诊", "就诊中", "住院中", "已康复", "慢性病随访")
SORT_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "ownerName",
    "species",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
    "createdAt",
    "updatedAt",
)
ORDERS: tuple[str, ...] = ("asc", "desc")

Species = Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
Status = Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
SortBy = Literal[
    "id",
    "name",
    "ownerName",
    "species",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
    "createdAt",
    "updatedAt",
]
Order = Literal["asc", "desc"]


class ListPetsParams(BaseModel):
    """Strict, forward-validated shape of the ``list_pets`` tool arguments."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    q: str | None = None
    name: str | None = None
    ownerName: str | None = None
    ownerPhone: str | None = None
    species: Species | None = None
    doctor: str | None = None
    disease: str | None = None
    status: Status | None = None
    min: int | float | None = Field(default=None, ge=0, description="总花费下界")
    max: int | float | None = Field(default=None, ge=0, description="总花费上界")
    sortBy: SortBy | None = None
    order: Order | None = None
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=500)

    @model_validator(mode="after")
    def _check_min_max(self) -> "ListPetsParams":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min 不能大于 max")
        return self


def validate_arguments(raw: Any) -> tuple[ListPetsParams, None] | tuple[None, dict[str, Any]]:
    """Validate the raw tool call arguments.

    Returns ``(params, None)`` on success or ``(None, error_envelope)`` on
    failure. The raw dict is used (not the already-coerced tool kwargs) so that
    unknown fields are caught before the SDK's own argument model drops them.
    """
    if not isinstance(raw, dict):
        return None, validation_error({"arguments": "arguments must be a JSON object"})
    try:
        params = ListPetsParams.model_validate(raw)
    except ValidationError as exc:
        return None, validation_error(_format_validation_error(exc))
    return params, None


def _format_validation_error(exc: ValidationError) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for err in exc.errors():
        loc = err.get("loc", ())
        loc_str = ".".join(str(part) for part in loc) if loc else "_"
        ctx = err.get("ctx") or {}
        expected = ctx.get("expected") if isinstance(ctx, dict) else None
        msg = err.get("msg", "invalid value")
        if expected:
            msg = f"{msg}（可选值：{expected}）"
        details.setdefault(loc_str, []).append(msg)
    return details


async def handle_list_pets(raw: Any, client: RestClient) -> CallToolResult:
    """Run the full list_pets flow and always return a ``CallToolResult``."""
    params, error = validate_arguments(raw)
    if error is not None:
        return _to_result(error, is_error=True)

    try:
        data = await client.list_pets(params.model_dump(exclude_none=True, mode="json"))
    except BackendError as exc:
        logger.warning("list_pets backend failure: code=%s", exc.code)
        return _to_result(exc.to_envelope(), is_error=True)
    except Exception as exc:  # noqa: BLE001 - always answer with the unified envelope
        logger.exception("list_pets unexpected internal failure")
        return _to_result(
            error_envelope(INTERNAL_ERROR, f"unexpected internal error: {exc!r}"),
            is_error=True,
        )
    return _to_result(data, is_error=False)


def _to_result(structured: Any, *, is_error: bool) -> CallToolResult:
    text = json.dumps(structured, ensure_ascii=False, default=_json_default)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=structured,
        is_error=is_error,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return str(value)
    return str(value)


TOOL_DESCRIPTION = (
    "在宠物医院管理系统中查询宠物档案列表，等价于后端 GET /api/v1/pets。"
    "支持按关键词、宠物信息、医生/疾病/状态、总花费区间等过滤，并支持排序与分页。"
    "参数与后端查询参数一一对应；species/status/sortBy/order 必须使用后端真实存在的枚举值，"
    "page>=1，1<=pageSize<=500，min/max 为非负数字且 min<=max。"
    "成功时返回 data 对象：items（宠物数组，records/charges 可能为 null 或数组）、total、page、pageSize、totalPages、totalCost；"
    "失败时返回统一错误结构 {\"error\": {\"code\", \"message\", \"details\"}}。"
    "适用场景：结合多条件过滤检索宠物档案，再基于返回的 id 在后续步骤中展开详情或进行其他操作。"
)

# Per-parameter hints used to annotate the JSON input schema exposed by tools/list.
SCHEMA_PARAMS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("q", {"type": "string", "title": "q", "description": "全局搜索关键词（匹配宠物名/主人姓名/电话/诊断等，取并集）"}),
    ("name", {"type": "string", "title": "name", "description": "按宠物名称精确/模糊过滤"}),
    ("ownerName", {"type": "string", "title": "ownerName", "description": "按主人姓名过滤"}),
    ("ownerPhone", {"type": "string", "title": "ownerPhone", "description": "按主人联系电话过滤"}),
    ("species", {"type": "string", "title": "species", "description": "宠物物种，必须为后端枚举值", "enum": list(SPECIES)}),
    ("doctor", {"type": "string", "title": "doctor", "description": "按负责医生姓名过滤"}),
    ("disease", {"type": "string", "title": "disease", "description": "按诊断疾病过滤"}),
    (
        "status",
        {"type": "string", "title": "status", "description": "就诊状态，必须为后端枚举值", "enum": list(STATUSES)},
    ),
    (
        "min",
        {"type": "number", "title": "min", "description": "总花费下界（>=0，仅数字，不接受 NaN/Infinity），与 max 同时给出时 min<=max"},
    ),
    (
        "max",
        {"type": "number", "title": "max", "description": "总花费上界（>=0，仅数字，不接受 NaN/Infinity），与 min 同时给出时 min<=max"},
    ),
    ("sortBy", {"type": "string", "title": "sortBy", "description": "排序字段，必须为后端枚举值", "enum": list(SORT_FIELDS)}),
    ("order", {"type": "string", "title": "order", "description": "排序方向", "enum": ["asc", "desc"]}),
    ("page", {"type": "integer", "title": "page", "description": "页码，从 1 开始", "minimum": 1}),
    ("pageSize", {"type": "integer", "title": "pageSize", "description": "每页条数，1-500", "minimum": 1, "maximum": 500}),
)

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20