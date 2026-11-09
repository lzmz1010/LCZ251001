"""Environment-driven configuration for the pet hospital MCP server.

All values can be overridden through environment variables so the service can
be deployed without code changes:

* ``PET_HOSPITAL_BASE_URL``   - upstream Go backend base URL (default ``http://127.0.0.1:8080``)
* ``PET_HOSPITAL_TIMEOUT``    - per-attempt request timeout in seconds (default ``10``)
* ``PET_HOSPITAL_RETRIES``    - retries after a failed attempt, before reporting an error (default ``2``)
* ``MCP_HOST``                - address to bind the MCP server to (default ``127.0.0.1``)
* ``MCP_PORT``                - TCP port to bind the MCP server to (default ``8000``)
* ``MCP_LOG_LEVEL``           - root log level (default ``INFO``)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

DEFAULT_PET_HOSPITAL_BASE_URL: str = "http://127.0.0.1:8080"
DEFAULT_PET_HOSPITAL_TIMEOUT: float = 10.0
DEFAULT_PET_HOSPITAL_RETRIES: int = 2
DEFAULT_MCP_HOST: str = "127.0.0.1"
DEFAULT_MCP_PORT: int = 8000
DEFAULT_LOG_LEVEL: str = "INFO"

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass(frozen=True)
class Settings:
    """Resolved, immutable service configuration."""

    pet_hospital_base_url: str
    pet_hospital_timeout: float
    pet_hospital_retries: int
    mcp_host: str
    mcp_port: int
    log_level: str

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "Settings":
        env = dict(os.environ if environ is None else environ)

        base_url = env.get("PET_HOSPITAL_BASE_URL", DEFAULT_PET_HOSPITAL_BASE_URL).strip().rstrip("/")
        if not base_url:
            base_url = DEFAULT_PET_HOSPITAL_BASE_URL
        if not base_url.startswith(("http://", "https://")):
            base_url = f"http://{base_url}"

        timeout = _parse_float(env.get("PET_HOSPITAL_TIMEOUT"), DEFAULT_PET_HOSPITAL_TIMEOUT)
        retries = _parse_int(env.get("PET_HOSPITAL_RETRIES"), DEFAULT_PET_HOSPITAL_RETRIES)
        host = env.get("MCP_HOST", DEFAULT_MCP_HOST).strip() or DEFAULT_MCP_HOST
        port = _parse_int(env.get("MCP_PORT"), DEFAULT_MCP_PORT)
        log_level = env.get("MCP_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
        if log_level not in VALID_LOG_LEVELS:
            log_level = DEFAULT_LOG_LEVEL

        return cls(
            pet_hospital_base_url=base_url,
            pet_hospital_timeout=timeout,
            pet_hospital_retries=retries,
            mcp_host=host,
            mcp_port=port,
            log_level=log_level,
        )


def _parse_int(raw: Optional[str], default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def _parse_float(raw: Optional[str], default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default