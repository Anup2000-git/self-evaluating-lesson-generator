"""Langfuse tracing: every pipeline node, agent step, tool call and LLM call of a run in one trace.

* **One trace per run.** The trace id is derived from the run id (``trace_id_for_run``), so
  every container - and a worker that resumes a crashed run - writes into the same trace.
* **Nested across services.** The orchestrator opens a span per pipeline node;
  ``ServiceClient`` forwards the active span as a W3C ``traceparent`` header; the called
  service opens its operation span as a child. The tree reads
  node -> service operation -> agent graph -> tool calls / LLM generations.
* **No plumbing in agent code.** Inside an operation a Langfuse LangChain callback handler is
  registered through a LangChain configure hook, so every model call, LangGraph run and
  structured-output call is captured without passing ``callbacks=`` around.
* **Optional and harmless.** Without LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (or with
  LANGFUSE_TRACING_ENABLED=false) everything here is a no-op. Spans are exported in the
  background, so a Langfuse outage never fails or slows down a request.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from lessongen_common.context import get_context
from lessongen_common.logs import get_logger

log = get_logger(__name__)

TRACE_NAME = "lesson-run"
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


class TracingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LANGFUSE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    public_key: str | None = None
    secret_key: SecretStr | None = None
    # Where the SDK sends spans (inside docker compose: http://langfuse-web:3000).
    base_url: str = "http://localhost:3000"
    # Browser-facing address of the Langfuse UI, used for "open trace" links.
    ui_url: str = "http://localhost:3000"
    # Project id for deep links; equals LANGFUSE_INIT_PROJECT_ID of the self-hosted server.
    project_id: str | None = None
    tracing_enabled: bool = True
    sample_rate: float = 1.0

    @property
    def enabled(self) -> bool:
        return bool(
            self.tracing_enabled
            and self.public_key
            and self.secret_key is not None
            and self.secret_key.get_secret_value()
        )

    def trace_url(self, run_id: str) -> str | None:
        """Deep link to a run's trace in the Langfuse UI (None when tracing is off)."""
        if not self.enabled or not self.project_id:
            return None
        return (
            f"{self.ui_url.rstrip('/')}/project/{self.project_id}/traces/{trace_id_for_run(run_id)}"
        )


def trace_id_for_run(run_id: str) -> str:
    """The run's trace id: same algorithm as ``Langfuse.create_trace_id(seed=run_id)``."""
    return hashlib.sha256(run_id.encode("utf-8")).digest()[:16].hex()


def _parse_traceparent(value: str | None) -> tuple[int, int] | None:
    match = _TRACEPARENT.match(value or "")
    if match is None:
        return None
    trace_id, span_id = int(match.group(1), 16), int(match.group(2), 16)
    return (trace_id, span_id) if trace_id and span_id else None


def _environment_name(value: str | None) -> str | None:
    # Langfuse: lowercase [a-z0-9_-], at most 40 characters, must not start with "langfuse".
    name = re.sub(r"[^a-z0-9_-]+", "-", (value or "").lower()).strip("-")[:40]
    return name if name and not name.startswith("langfuse") else None


# Holds the LangChain callback handler of the operation that is running in this context.
# Registered once as a LangChain configure hook: every LangChain/LangGraph run started while
# it is set reports to Langfuse, nested under the operation span.
_handler: ContextVar[Any | None] = ContextVar("lessongen_langfuse_handler", default=None)
_hook_registered = False


def _register_langchain_hook() -> None:
    global _hook_registered
    if _hook_registered:
        return
    from langchain_core.tracers.context import register_configure_hook

    register_configure_hook(_handler, inheritable=True)
    _hook_registered = True


class SpanHandle:
    """What ``Tracer.span`` yields: lets the caller attach output and metadata. Never raises."""

    def __init__(self, observation: Any = None) -> None:
        self._observation = observation

    @property
    def trace_id(self) -> str | None:
        return getattr(self._observation, "trace_id", None)

    @property
    def span_id(self) -> str | None:
        return getattr(self._observation, "id", None)

    def update(self, **fields: Any) -> None:
        if self._observation is None:
            return
        try:
            self._observation.update(**fields)
        except Exception as exc:  # tracing must never break the operation
            log.debug("tracing_update_failed", error=str(exc))


_NOOP_SPAN = SpanHandle()


class Tracer:
    """Per-process tracing facade. Every method is a no-op when Langfuse is not configured."""

    def __init__(
        self,
        service: str,
        settings: TracingSettings | None = None,
        *,
        release: str | None = None,
        environment: str | None = None,
        tracer_provider: Any = None,
        span_exporter: Any = None,
    ) -> None:
        self.service = service
        self.settings = settings or TracingSettings()
        self._client: Any = None
        if not self.settings.enabled:
            return
        try:
            from langfuse import Langfuse

            assert self.settings.secret_key is not None
            self._client = Langfuse(
                public_key=self.settings.public_key,
                secret_key=self.settings.secret_key.get_secret_value(),
                base_url=self.settings.base_url,
                environment=_environment_name(environment),
                release=release,
                sample_rate=self.settings.sample_rate,
                tracer_provider=tracer_provider,
                span_exporter=span_exporter,
            )
            _register_langchain_hook()
            log.info("tracing_enabled", backend="langfuse", base_url=self.settings.base_url)
        except Exception as exc:  # a tracing misconfiguration must not take the service down
            log.warning("tracing_disabled", error=str(exc))
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def trace_url(self, run_id: str) -> str | None:
        return self.settings.trace_url(run_id) if self.enabled else None

    async def health(self) -> dict[str, Any]:
        """Status for the System page: enabled, UI link and whether the server answers."""
        if not self.enabled:
            return {"enabled": False}
        info: dict[str, Any] = {
            "enabled": True,
            "ui_url": self.settings.ui_url,
            "project_id": self.settings.project_id,
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{self.settings.base_url.rstrip('/')}/api/public/health"
                )
            info["ok"] = response.status_code == 200
            info["version"] = (response.json() if response.content else {}).get("version")
        except Exception as exc:
            info["ok"] = False
            info["error"] = str(exc)[:200]
        return info

    @contextlib.contextmanager
    def span(
        self,
        name: str,
        *,
        as_type: str = "span",
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        trace_name: str | None = None,
        tags: list[str] | None = None,
        capture_llm: bool = True,
    ) -> Iterator[SpanHandle]:
        """Open a span for an operation of the current run; LLM calls inside are captured.

        Parent, in order of preference: the active span in this process, the caller's span
        (``traceparent`` header), else a root span in the run's trace (or a new trace when
        there is no run).
        """
        if self._client is None:
            yield _NOOP_SPAN
            return
        stack = contextlib.ExitStack()
        try:
            observation = self._open(stack, name, as_type, input, metadata, trace_name, tags)
            if capture_llm:
                from langfuse.langchain import CallbackHandler

                token = _handler.set(CallbackHandler(public_key=self.settings.public_key))
                stack.callback(_handler.reset, token)
        except Exception as exc:  # tracing must never break the operation
            stack.close()
            log.warning("tracing_span_failed", span=name, error=str(exc))
            yield _NOOP_SPAN
            return
        with stack:
            handle = SpanHandle(observation)
            try:
                yield handle
            except BaseException as exc:
                handle.update(level="ERROR", status_message=f"{type(exc).__name__}: {exc}"[:500])
                raise

    def _open(
        self,
        stack: contextlib.ExitStack,
        name: str,
        as_type: str,
        input: Any,
        metadata: dict[str, Any] | None,
        trace_name: str | None,
        tags: list[str] | None,
    ) -> Any:
        from langfuse import propagate_attributes
        from opentelemetry import context as otel_context
        from opentelemetry import trace as otel_trace

        ctx = get_context()
        trace_context: dict[str, str] | None = None
        if not otel_trace.get_current_span().get_span_context().is_valid:
            remote = _parse_traceparent(ctx.trace_parent)
            if remote is not None:
                parent = otel_trace.NonRecordingSpan(
                    otel_trace.SpanContext(
                        trace_id=remote[0],
                        span_id=remote[1],
                        is_remote=True,
                        trace_flags=otel_trace.TraceFlags(otel_trace.TraceFlags.SAMPLED),
                    )
                )
                token = otel_context.attach(otel_trace.set_span_in_context(parent))
                stack.callback(otel_context.detach, token)
            elif ctx.run_id:
                trace_context = {"trace_id": trace_id_for_run(ctx.run_id)}

        span_metadata: dict[str, Any] = {"service": self.service}
        if ctx.node:
            span_metadata["node"] = ctx.node
        if ctx.attempt is not None:
            span_metadata["attempt"] = ctx.attempt
        span_metadata.update(metadata or {})
        observation = stack.enter_context(
            self._client.start_as_current_observation(
                name=name,
                as_type=as_type,
                input=input,
                metadata=span_metadata,
                trace_context=trace_context,
            )
        )
        stack.enter_context(
            propagate_attributes(
                session_id=ctx.run_id,
                trace_name=trace_name,
                tags=tags,
                metadata={"run_id": ctx.run_id} if ctx.run_id else None,
            )
        )
        return observation

    def flush(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
            except Exception as exc:
                log.warning("tracing_flush_failed", error=str(exc))

    def shutdown(self) -> None:
        if self._client is not None:
            try:
                self._client.shutdown()
            except Exception as exc:
                log.warning("tracing_shutdown_failed", error=str(exc))
            self._client = None


_tracer = Tracer("unconfigured", TracingSettings.model_construct(tracing_enabled=False))


def configure_tracing(
    service: str,
    *,
    release: str | None = None,
    environment: str | None = None,
    settings: TracingSettings | None = None,
) -> Tracer:
    """Create this process's tracer (call once at startup; ``Tracer.shutdown`` at exit)."""
    global _tracer
    _tracer = Tracer(service, settings, release=release, environment=environment)
    return _tracer


def get_tracer() -> Tracer:
    return _tracer
