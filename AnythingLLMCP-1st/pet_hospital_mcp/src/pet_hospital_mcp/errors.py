"""Unified error envelope used by the pet hospital MCP server.

Every tool failure is reported to the client as a :class:`CallToolResult` with
``is_error=True`` whose ``structured_content`` carries exactly

    {"error": {"code": "ERROR_CODE", "message": "readable message", "details": {...}}}

following the `v2 tool error handling contract
<https://py.sdk.modelcontextprotocol.io/servers/handling-errors/>`_: tool errors
are reported *inside* the result (so the model can read and self-correct), not
as JSON-RPC protocol errors.
"""

from __future__ import annotations

from typing import Any, Mapping

VALIDATION_ERROR = "VALIDATION_ERROR"
BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
BACKEND_API_ERROR = "BACKEND_API_ERROR"
BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
INTERNAL_ERROR = "INTERNAL_ERROR"

_KNOWN_CODES = frozenset(
    {
        VALIDATION_ERROR,
        BACKEND_TIMEOUT,
        BACKEND_UNAVAILABLE,
        BACKEND_API_ERROR,
        BACKEND_INVALID_RESPONSE,
        INTERNAL_ERROR,
    }
)


def error_envelope(
    code: str,
    message: str,
    details: Mapping[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Build a unified error envelope dict ``{"error": {...}}``."""
    if code not in _KNOWN_CODES:
        code = INTERNAL_ERROR
    return {"error": {"code": code, "message": message, "details": dict(details or {})}}


def validation_error(details: Mapping[str, Any] | list[Any] | None = None) -> dict[str, Any]:
    return error_envelope(
        VALIDATION_ERROR,
        "参数校验失败，请根据 details 修正请求后重试",
        details,
    )


class BackendError(Exception):
    """Base class for failures while talking to the pet hospital Go backend."""

    code: str = BACKEND_API_ERROR

    def __init__(self, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_envelope(self) -> dict[str, Any]:
        return error_envelope(self.code, self.message, self.details)


class BackendTimeoutError(BackendError):
    code = BACKEND_TIMEOUT


class BackendUnavailableError(BackendError):
    code = BACKEND_UNAVAILABLE


class BackendApiError(BackendError):
    code = BACKEND_API_ERROR


class BackendInvalidResponseError(BackendError):
    code = BACKEND_INVALID_RESPONSE