"""Logging configuration for the pet hospital MCP server.

A :class:`SensitiveDataFilter` is installed on every handler so that secrets
(API keys, bearer tokens, ``Authorization`` headers, passwords ...) never reach
the log output, regardless of which component logs the line.

Tools emit structured JSON log lines that carry the metadata required by the
project contract - ``timestamp``, ``tool_name``, ``params``, ``status`` and
``duration_ms`` - with pet-owner personally-identifiable fields
(``ownerPhone`` / ``ownerAddr`` / ``chipNo`` and their snake_case spellings)
recursively redacted by :func:`redact_pii` before anything is written.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Final

_LOG_FIELDS: Final[tuple[str, ...]] = ("tool_name", "params", "status", "duration_ms")

# PII keys redacted from log payloads (ownerPhone / ownerAddr / chipNo plus
# snake_case). Keys are matched case-insensitively with internal underscores
# ignored, so camelCase and snake_case spellings are both caught.
_SENSITIVE_KEY_NORM: Final[frozenset[str]] = frozenset({"ownerphone", "owneraddr", "chipno"})


def _normalize_key(key: Any) -> str | None:
    if not isinstance(key, str):
        return None
    return key.lower().replace("_", "")


def redact_pii(value: Any) -> Any:
    """Return ``value`` with pet-owner PII recursively masked.

    Any dict entry whose key is ``ownerPhone``, ``ownerAddr``, ``chipNo`` (or a
    snake_case / mixed variant) has its value replaced with ``"***"`` - both at
    the top level and anywhere it appears inside nested dicts or lists.
    """
    if isinstance(value, Mapping):
        return {
            key: "***" if _normalize_key(key) in _SENSITIVE_KEY_NORM else redact_pii(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_pii(item) for item in value]
    return value

_REDACTIONS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # authorization / proxy-authorization headers: `Authorization: Bearer xxx`
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"), r"\1***"),
    # generic "bearer <token>" mentions
    (re.compile(r"(?i)(\bbearer\s+)[a-z0-9._~+/-]+=*", re.MULTILINE), r"\1***"),
    # key=value style secrets
    (re.compile(r"(?i)((?:api[-_]?key|access[-_]?token|refresh[-_]?token|token|secret|password)\s*=\s*)\S+"), r"\1***"),
    # JSON-ish "key": "value" secrets
    (
        re.compile(r'(?i)(["\']?(?:api[-_]?key|x-api-key|access[-_]?token|refresh[-_]?token|token|secret|password)["\']?\s*[:=]\s*["\']?)[^"\'`,}\s]{4,}'),
        r"\1***",
    ),
    # plausible API keys (sk-..., 32+-char opaque tokens) even without a label
    (re.compile(r"\bsk-[a-z0-9_-]{8,}\b"), "sk-***"),
    (re.compile(r"\b(?:[a-f0-9]{32}|[a-f0-9]{64})\b"), "***"),
)


class SensitiveDataFilter(logging.Filter):
    """Redact secrets from log records before they hit a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for pattern, replacement in _REDACTIONS:
            redacted = pattern.sub(replacement, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Emit one structured JSON object per log line.

    Always includes ``timestamp`` plus the tool metadata supplied via ``extra``
    (``tool_name``, ``params``, ``status``, ``duration_ms``) when present.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _LOG_FIELDS:
            value = record.__dict__.get(key)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    """Configure the root logger with a JSON console handler and redaction."""
    root = logging.getLogger()
    root.setLevel(level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else logging.INFO)

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SensitiveDataFilter())
    root.addHandler(handler)