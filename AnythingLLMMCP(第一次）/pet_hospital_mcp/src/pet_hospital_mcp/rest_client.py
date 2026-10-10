"""Async HTTP client for the pet hospital Go backend.

Responsibilities:

* build and issue ``GET /api/v1/pets`` with validated query parameters,
* enforce per-attempt timeouts and a limited number of retries,
* classify every failure into one of the :mod:`pet_hospital_mcp.errors`
  error codes (``BACKEND_TIMEOUT``, ``BACKEND_UNAVAILABLE``, ``BACKEND_API_ERROR``,
  ``BACKEND_INVALID_RESPONSE``).

No authentication headers are ever attached - the upstream Go service is
unauthenticated and there are no secrets to forward.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

import httpx

from .errors import (
    BackendApiError,
    BackendInvalidResponseError,
    BackendTimeoutError,
    BackendUnavailableError,
)

logger = logging.getLogger("pet_hospital_mcp.rest_client")

PETS_PATH = "/api/v1/pets"


class RestClient:
    """Thin, dependency-injectable HTTP client around the Go backend."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.retries = max(0, int(retries))
        timeout = httpx.Timeout(self.timeout_seconds, connect=self.timeout_seconds)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    @property
    def attempts_allowed(self) -> int:
        return self.retries + 1

    async def list_pets(self, query: Mapping[str, Any]) -> dict[str, Any]:
        """Fetch a page of pets and return the parsed ``data`` object.

        ``None`` values are dropped so only the caller-provided filters are put
        on the wire.
        """
        params = {key: value for key, value in query.items() if value is not None}

        last_exc: BaseException | None = None
        for attempt in range(1, self.attempts_allowed + 1):
            try:
                response = await self._client.get(PETS_PATH, params=params)
                return self._parse_response(response)
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("pet hospital backend timed out on attempt %s/%s", attempt, self.attempts_allowed)
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning("pet hospital backend unreachable on attempt %s/%s", attempt, self.attempts_allowed)
            if attempt < self.attempts_allowed:
                await asyncio.sleep(0.2 * attempt)

        assert last_exc is not None
        if isinstance(last_exc, httpx.TimeoutException):
            raise BackendTimeoutError(
                f"pet hospital backend timed out after {self.attempts_allowed} attempts",
                {"path": PETS_PATH, "attempts": self.attempts_allowed},
            ) from last_exc
        if isinstance(last_exc, httpx.ConnectError) or isinstance(last_exc, httpx.ConnectTimeout):
            raise BackendUnavailableError(
                f"pet hospital backend is unreachable at {self.base_url}",
                {"path": PETS_PATH, "attempts": self.attempts_allowed},
            ) from last_exc
        raise BackendUnavailableError(
            f"pet hospital backend is unavailable: {last_exc}",
            {"path": PETS_PATH, "attempts": self.attempts_allowed},
        ) from last_exc

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        if not 200 <= response.status_code < 300:
            raise BackendApiError(
                f"pet hospital backend returned HTTP {response.status_code}",
                {"path": PETS_PATH, "status_code": response.status_code},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise BackendInvalidResponseError(
                "pet hospital backend returned a non-JSON body",
                {"path": PETS_PATH, "status_code": response.status_code},
            ) from exc
        if not isinstance(payload, dict):
            raise BackendInvalidResponseError(
                "pet hospital backend returned a non-object JSON body",
                {"path": PETS_PATH, "body_type": type(payload).__name__},
            )
        if payload.get("code") != 200:
            raise BackendApiError(
                f"pet hospital backend reported an API error: {payload.get('message', 'unknown')}",
                {"path": PETS_PATH, "code": payload.get("code"), "message": payload.get("message")},
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise BackendInvalidResponseError(
                "pet hospital backend response is missing a data object",
                {"path": PETS_PATH, "data_type": type(data).__name__ if data is not None else "null"},
            )
        return data

    async def aclose(self) -> None:
        await self._client.aclose()