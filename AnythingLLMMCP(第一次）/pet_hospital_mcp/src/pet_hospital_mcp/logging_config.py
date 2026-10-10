"""Logging configuration for the pet hospital MCP server.

A :class:`SensitiveDataFilter` is installed on every handler so that secrets
(API keys, bearer tokens, ``Authorization`` headers, passwords ...) never reach
the log output, regardless of which component logs the line.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Final

_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s: %(message)s"

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


def configure_logging(level: str) -> None:
    """Configure the root logger with a console handler and secret redaction."""
    root = logging.getLogger()
    root.setLevel(level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else logging.INFO)

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(SensitiveDataFilter())
    root.addHandler(handler)