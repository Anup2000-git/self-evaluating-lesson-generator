"""Resilient service-to-service HTTP client.

* Propagates ``X-Request-ID`` / ``X-Run-ID`` / ``X-Attempt`` / ``X-Node`` from the context.
* Retries only failures where the request almost certainly did not run (connection
  errors) or the upstream said "try again" (502/503/504). Read timeouts are NOT retried:
  an LLM call may still be running and re-sending it would double the cost.
* Turns non-2xx responses into ``ServiceError`` carrying the upstream problem detail.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from lessongen_common.context import outgoing_headers
from lessongen_common.errors import ServiceError
from lessongen_common.logs import get_logger

log = get_logger(__name__)

_RETRY_STATUSES = {502, 503, 504}


class _RetryableStatus(Exception):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"retryable status {response.status_code}")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(
        exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, _RetryableStatus)
    )


class ServiceClient:
    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        timeout: float = 30.0,
        connect_timeout: float = 5.0,
        retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.retries = retries
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        request_timeout = (
            httpx.Timeout(timeout, connect=self._client.timeout.connect)
            if timeout is not None
            else None
        )
        response: httpx.Response | None = None
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(_is_retryable),
                stop=stop_after_attempt(self.retries + 1),
                wait=wait_exponential_jitter(multiplier=0.5, max=8.0),
                reraise=True,
            ):
                with attempt:
                    kwargs: dict[str, Any] = {
                        "json": json,
                        "params": params,
                        "headers": outgoing_headers(),
                    }
                    if request_timeout is not None:
                        kwargs["timeout"] = request_timeout
                    response = await self._client.request(method, path, **kwargs)
                    if response.status_code in _RETRY_STATUSES:
                        raise _RetryableStatus(response)
        except _RetryableStatus as exc:
            response = exc.response
        except httpx.TimeoutException as exc:
            raise ServiceError(self.name, None, f"timeout calling {method} {path}") from exc
        except httpx.TransportError as exc:
            raise ServiceError(self.name, None, f"cannot reach {self.name}: {exc!s}") from exc

        assert response is not None
        if response.status_code >= 400:
            body: Any
            try:
                body = response.json()
            except ValueError:
                body = response.text
            detail = body.get("detail") if isinstance(body, dict) else str(body)
            raise ServiceError(self.name, response.status_code, str(detail)[:2000], body)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", path, **kwargs)

    async def ping(self, path: str = "/readyz") -> dict[str, Any]:
        """Best-effort readiness probe used by the System page."""
        try:
            response = await self._client.get(path, timeout=3.0, headers=outgoing_headers())
            payload = response.json() if response.content else {}
            return {"ok": response.status_code == 200, "status": response.status_code, **payload}
        except Exception as exc:
            return {"ok": False, "status": None, "error": str(exc)}
