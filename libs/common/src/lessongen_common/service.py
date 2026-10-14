"""FastAPI application factory used by every microservice.

Gives each service the same production baseline: structured logging, correlation-id
middleware, RFC 7807-style error bodies, ``/healthz`` (liveness) and ``/readyz``
(readiness with dependency checks), optional CORS, a Redis-backed event bus and
Langfuse tracing (when configured).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lessongen_common.context import HEADER_REQUEST_ID, context_from_headers, set_context
from lessongen_common.errors import (
    LessongenError,
    LLMNotConfiguredError,
    NotFoundError,
    ServiceError,
)
from lessongen_common.events import EventBus, configure_event_bus
from lessongen_common.logs import configure_logging, get_logger
from lessongen_common.settings import ServiceSettings
from lessongen_common.tracing import configure_tracing

log = get_logger(__name__)

ReadinessCheck = Callable[[], Awaitable[Any]]
Lifespan = Callable[[FastAPI], Any]


class RequestContextMiddleware:
    """Pure ASGI middleware (safe for streaming/SSE) that restores the caller's run context."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        ctx = context_from_headers(headers)
        set_context(ctx)
        started = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                raw_headers = list(message.get("headers", []))
                raw_headers.append((HEADER_REQUEST_ID.lower().encode(), ctx.request_id.encode()))  # type: ignore[union-attr]
                message["headers"] = raw_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path not in ("/healthz", "/readyz"):
                log.info(
                    "http_request",
                    method=scope.get("method"),
                    path=path,
                    status=status_holder.get("status"),
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )


def _problem(status: int, title: str, detail: Any, request: Request) -> JSONResponse:
    from lessongen_common.context import get_context

    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": request.url.path,
            "request_id": get_context().request_id,
        },
        media_type="application/problem+json",
    )


def create_service_app(
    *,
    name: str,
    version: str,
    settings: ServiceSettings,
    description: str = "",
    lifespan: Callable[[FastAPI], Any] | None = None,
    readiness_checks: dict[str, ReadinessCheck] | None = None,
    use_redis: bool = True,
    redis_client: Redis | None = None,
) -> FastAPI:
    configure_logging(name, settings.log_level, settings.log_json)
    checks: dict[str, ReadinessCheck] = dict(readiness_checks or {})

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        redis: Redis | None = redis_client
        if redis is None and use_redis and settings.events_enabled:
            redis = Redis.from_url(
                settings.redis_url,
                socket_timeout=settings.redis_socket_timeout_seconds,
                socket_connect_timeout=3,
                health_check_interval=30,
            )
        if redis is not None:
            checks.setdefault("redis", redis.ping)
        app.state.redis = redis
        configure_event_bus(
            EventBus(
                redis,
                name,
                maxlen=settings.event_stream_maxlen,
                ttl_seconds=settings.event_stream_ttl_days * 24 * 3600,
            )
        )
        tracer = configure_tracing(name, release=version, environment=settings.environment)
        log.info("service_starting", version=version, environment=settings.environment)
        try:
            if lifespan is not None:
                async with lifespan(app):
                    yield
            else:
                yield
        finally:
            tracer.shutdown()  # flushes buffered spans
            configure_event_bus(None)
            if redis is not None and redis_client is None:
                await redis.aclose()
            log.info("service_stopped")

    app = FastAPI(
        title=f"{name} service",
        version=version,
        description=description,
        root_path=settings.root_path,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        return _problem(exc.status_code, "HTTP error", exc.detail, request)

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return _problem(422, "Validation error", errors, request)

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return _problem(404, "Not found", str(exc), request)

    @app.exception_handler(LLMNotConfiguredError)
    async def _llm_missing(request: Request, exc: LLMNotConfiguredError) -> JSONResponse:
        # 424 Failed Dependency: a configuration problem, so callers must not retry it.
        return _problem(424, "LLM not configured", str(exc), request)

    @app.exception_handler(ServiceError)
    async def _upstream(request: Request, exc: ServiceError) -> JSONResponse:
        log.warning("upstream_error", upstream=exc.service, status=exc.status, detail=exc.detail)
        status = exc.status if exc.status in (400, 404, 409, 422) else 502
        return _problem(status, f"Upstream error from {exc.service}", exc.detail, request)

    @app.exception_handler(LessongenError)
    async def _domain(request: Request, exc: LessongenError) -> JSONResponse:
        log.warning("domain_error", error_type=type(exc).__name__, error=str(exc))
        return _problem(422, type(exc).__name__, str(exc), request)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error_type=type(exc).__name__)
        return _problem(500, "Internal server error", "unexpected error; see service logs", request)

    @app.get("/healthz", tags=["ops"], summary="Liveness probe")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": name, "version": version}

    @app.get("/readyz", tags=["ops"], summary="Readiness probe (checks dependencies)")
    async def readyz() -> JSONResponse:
        results: dict[str, str] = {}
        ok = True
        for check_name, check in checks.items():
            try:
                await check()
                results[check_name] = "ok"
            except Exception as exc:
                ok = False
                results[check_name] = f"error: {str(exc)[:200]}"
        return JSONResponse(
            status_code=200 if ok else 503,
            content={
                "status": "ready" if ok else "not_ready",
                "service": name,
                "version": version,
                "checks": results,
            },
        )

    return app


def serve(app_path: str, settings: ServiceSettings) -> None:
    """Run a service with uvicorn, keeping our structured logging configuration."""
    import uvicorn

    uvicorn.run(
        app_path,
        host=settings.service_host,
        port=settings.service_port,
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips="*",
        timeout_graceful_shutdown=20,
    )
