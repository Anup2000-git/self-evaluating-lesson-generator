"""Request/run correlation that flows through every service call.

The orchestrator sets the run context; ``ServiceClient`` forwards it as headers; the
receiving service's middleware restores it. Logs, events and usage records therefore all
carry the same ``run_id`` no matter which container produced them. The active tracing span
travels the same way as a W3C ``traceparent`` header (see ``lessongen_common.tracing``).
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, replace

HEADER_REQUEST_ID = "X-Request-ID"
HEADER_RUN_ID = "X-Run-ID"
HEADER_ATTEMPT = "X-Attempt"
HEADER_NODE = "X-Node"
HEADER_TRACEPARENT = "traceparent"


@dataclass(frozen=True, slots=True)
class RunContext:
    request_id: str | None = None
    run_id: str | None = None
    attempt: int | None = None
    node: str | None = None
    # The caller's span (W3C traceparent); the service's tracing span becomes its child.
    trace_parent: str | None = None


_EMPTY = RunContext()
_current: ContextVar[RunContext | None] = ContextVar("lessongen_run_context", default=None)


def get_context() -> RunContext:
    return _current.get() or _EMPTY


@contextlib.contextmanager
def bind_context(**changes: object) -> Iterator[RunContext]:
    """Temporarily overlay fields (run_id, attempt, node, request_id) on the current context."""
    ctx = replace(get_context(), **changes)  # type: ignore[arg-type]
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def set_context(ctx: RunContext) -> None:
    _current.set(ctx)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def outgoing_headers() -> dict[str, str]:
    ctx = get_context()
    headers = {HEADER_REQUEST_ID: ctx.request_id or new_request_id()}
    if ctx.run_id:
        headers[HEADER_RUN_ID] = ctx.run_id
    if ctx.attempt is not None:
        headers[HEADER_ATTEMPT] = str(ctx.attempt)
    if ctx.node:
        headers[HEADER_NODE] = ctx.node
    traceparent = _active_traceparent()
    if traceparent:
        headers[HEADER_TRACEPARENT] = traceparent
    return headers


def _active_traceparent() -> str | None:
    """W3C traceparent of the active OpenTelemetry span (set by the tracing module), if any."""
    try:
        from opentelemetry import trace
    except ImportError:  # tracing is an optional extra
        return None
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return (
        f"00-{span_context.trace_id:032x}-{span_context.span_id:016x}"
        f"-{int(span_context.trace_flags):02x}"
    )


def context_from_headers(headers: dict[str, str]) -> RunContext:
    lowered = {k.lower(): v for k, v in headers.items()}
    attempt_raw = lowered.get(HEADER_ATTEMPT.lower())
    try:
        attempt = int(attempt_raw) if attempt_raw is not None else None
    except ValueError:
        attempt = None
    return RunContext(
        request_id=lowered.get(HEADER_REQUEST_ID.lower()) or new_request_id(),
        run_id=lowered.get(HEADER_RUN_ID.lower()) or None,
        attempt=attempt,
        node=lowered.get(HEADER_NODE.lower()) or None,
        trace_parent=lowered.get(HEADER_TRACEPARENT) or None,
    )
