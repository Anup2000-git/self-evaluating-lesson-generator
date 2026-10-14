"""Orchestrator API: the public entry point for runs (create, watch live, cancel, resume, export)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request, Response, status
from sse_starlette.sse import EventSourceResponse

from lessongen_common.events import EventBus, get_event_bus
from lessongen_common.llm import LLMProvider
from lessongen_common.llm.doctor import run_doctor
from lessongen_common.rendering import lesson_to_markdown, rejection_log_to_markdown
from lessongen_common.schemas import (
    TERMINAL_EVENT_TYPES,
    TERMINAL_STATUSES,
    ConsolidationResult,
    Event,
    EventType,
    RunCreate,
    RunDetail,
    RunList,
    RunMode,
    RunRecord,
    RunRequest,
    RunStatus,
    TopicPackSummary,
)
from lessongen_common.service import create_service_app
from lessongen_common.tracing import get_tracer
from orchestrator_svc import __version__
from orchestrator_svc.jobs import Job, JobQueue, cancel_key
from orchestrator_svc.settings import OrchestratorSettings
from orchestrator_svc.wiring import Clients, build_clients

router = APIRouter(prefix="/v1")
JOB_TTL_SECONDS = 7 * 24 * 3600


def _clients(request: Request) -> Clients:
    return request.app.state.clients


def _queue(request: Request) -> JobQueue:
    return request.app.state.queue


def _job_key(run_id: str) -> str:
    return f"job:run:{run_id}"


# ---------------------------------------------------------------------- runs
@router.post("/runs", response_model=RunRecord, status_code=status.HTTP_202_ACCEPTED, tags=["runs"])
async def create_run(body: RunRequest, request: Request) -> RunRecord:
    """Queue a run. Watch it live with GET /v1/runs/{id}/events (Server-Sent Events)."""
    settings: OrchestratorSettings = request.app.state.settings
    clients = _clients(request)
    resolution = await clients.knowledge.resolve(body.topic)
    if resolution is None:
        topics = ", ".join(t.title for t in await clients.knowledge.list_topics())
        raise HTTPException(
            status_code=422,
            detail=f"No grounded knowledge pack for '{body.topic}'. Available topics: {topics}. "
            "Lessons are only generated for topics the system can ground and fact-check.",
        )
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    record = await clients.memory.create_run(
        RunCreate(
            id=run_id,
            topic=body.topic,
            topic_id=resolution.topic_id,
            mode=body.mode,
            max_retries=min(body.max_retries, settings.max_retries)
            if body.mode != RunMode.EVALUATE_ONLY
            else 0,
            helper_language=body.helper_language,
            fault_id=body.fault_id,
            source_run_id=body.source_run_id,
        )
    )
    job = Job(
        run_id=run_id,
        mode=body.mode,
        topic=body.topic,
        topic_id=resolution.topic_id,
        topic_title=resolution.title,
        helper_language=body.helper_language,
        max_retries=record.max_retries,
        initial_lesson=body.initial_lesson,
        fault_id=body.fault_id,
    )
    redis = request.app.state.redis
    await redis.set(_job_key(run_id), job.model_dump_json(), ex=JOB_TTL_SECONDS)
    await _queue(request).enqueue(job)
    bus = get_event_bus()
    if bus is not None:
        await bus.publish(
            run_id,
            EventType.RUN_QUEUED,
            {
                "topic": body.topic,
                "topic_id": resolution.topic_id,
                "mode": body.mode.value,
                "max_retries": record.max_retries,
            },
        )
    return record


@router.get("/runs", response_model=RunList, tags=["runs"])
async def list_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    mode: str | None = None,
) -> RunList:
    return await _clients(request).memory.list_runs(
        limit=limit, offset=offset, status=status_filter, mode=mode
    )


@router.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"])
async def get_run(run_id: str, request: Request) -> RunDetail:
    run = await _clients(request).memory.get_run(run_id)
    run.trace_url = get_tracer().trace_url(run_id)
    return run


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED, tags=["runs"])
async def cancel_run(run_id: str, request: Request) -> dict[str, str]:
    """Ask the worker to stop the run before its next step."""
    run = await _clients(request).memory.get_run(run_id)
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"run is already {run.status.value}")
    await request.app.state.redis.set(cancel_key(run_id), "1", ex=24 * 3600)
    return {"run_id": run_id, "status": "cancel_requested"}


@router.post("/runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED, tags=["runs"])
async def resume_run(run_id: str, request: Request) -> dict[str, str]:
    """Re-queue a failed run; the worker continues from its last LangGraph checkpoint."""
    run = await _clients(request).memory.get_run(run_id)
    if run.status not in (RunStatus.FAILED, RunStatus.CANCELLED):
        raise HTTPException(
            status_code=409,
            detail=f"only failed or cancelled runs can resume (run is {run.status.value})",
        )
    redis = request.app.state.redis
    raw = await redis.get(_job_key(run_id))
    if raw is None:
        raise HTTPException(
            status_code=410, detail="the job for this run has expired; start a new run"
        )
    await redis.delete(cancel_key(run_id))
    await _queue(request).enqueue(Job.model_validate_json(raw))
    return {"run_id": run_id, "status": "resume_queued"}


@router.get("/runs/{run_id}/events", tags=["runs"])
async def run_events(
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    from_id: str | None = Query(default=None, alias="from"),
) -> EventSourceResponse:
    """Live progress as Server-Sent Events, replayable from any event id."""
    bus: EventBus | None = get_event_bus()
    settings: OrchestratorSettings = request.app.state.settings
    memory = _clients(request).memory
    start = last_event_id or from_id or "0-0"

    async def stream() -> AsyncIterator[dict[str, Any]]:
        if bus is None:
            return
        cursor = start
        idle_rounds = 0
        while True:
            if await request.is_disconnected():
                return
            events = await bus.read(run_id, cursor, block_ms=settings.sse_block_ms, count=200)
            if not events:
                idle_rounds += 1
                if idle_rounds >= 2 and cursor == "0-0":
                    # Nothing ever streamed (expired or unknown): close with the stored status.
                    run = await memory.get_run(run_id)
                    if run.status in TERMINAL_STATUSES:
                        synthetic = Event(
                            run_id=run_id,
                            ts=datetime.now(UTC),
                            service="orchestrator",
                            type=EventType.RUN_COMPLETED,
                            data={
                                "status": run.status.value,
                                "replayed": False,
                                "note": "event history expired",
                            },
                        )
                        yield {"data": synthetic.model_dump_json()}
                        return
                continue
            idle_rounds = 0
            for event in events:
                cursor = event.id or cursor
                yield {"id": event.id, "data": event.model_dump_json()}
                if event.type in TERMINAL_EVENT_TYPES:
                    return

    return EventSourceResponse(
        stream(), ping=15, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ------------------------------------------------------------------- exports
def _final_attempt(run: RunDetail):
    attempt = run.final_attempt() or (run.attempts[-1] if run.attempts else None)
    if attempt is None:
        raise HTTPException(status_code=404, detail="this run has no evaluated lesson yet")
    return attempt


@router.get("/runs/{run_id}/export/lesson.md", tags=["exports"], response_class=Response)
async def export_lesson(run_id: str, request: Request) -> Response:
    run = await _clients(request).memory.get_run(run_id)
    attempt = _final_attempt(run)
    body = lesson_to_markdown(attempt.lesson, helper_language=run.helper_language)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{run_id}-lesson.md"'},
    )


@router.get("/runs/{run_id}/export/rejection-log.md", tags=["exports"], response_class=Response)
async def export_rejection_log(run_id: str, request: Request) -> Response:
    run = await _clients(request).memory.get_run(run_id)
    return Response(
        content=rejection_log_to_markdown(run),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{run_id}-rejection-log.md"'},
    )


# -------------------------------------------------------------- learning/system
@router.get("/topics", response_model=list[TopicPackSummary], tags=["system"])
async def topics(request: Request) -> list[TopicPackSummary]:
    return await _clients(request).knowledge.list_topics()


@router.post("/learning/consolidate", response_model=ConsolidationResult, tags=["learning"])
async def consolidate_feedback(request: Request) -> ConsolidationResult:
    """Process pending human feedback into guidelines / rubric proposals now."""
    return await _clients(request).memory.consolidate(None)


@router.get("/system/status", tags=["system"])
async def system_status(request: Request) -> dict[str, Any]:
    """Health of every microservice, queue depth and the (secret-free) model configuration."""
    clients = _clients(request)
    settings: OrchestratorSettings = request.app.state.settings
    names = list(clients.http)
    pings = await asyncio.gather(*(clients.http[n].ping() for n in names))
    services = [{"name": "orchestrator-api", "ok": True, "status": 200, "version": __version__}]
    services += [{"name": n, **p} for n, p in zip(names, pings, strict=True)]
    try:
        queue = await _queue(request).depth()
    except Exception as exc:
        queue = {"error": str(exc)}
    provider: LLMProvider = request.app.state.llm
    return {
        "services": services,
        "queue": queue,
        "tracing": await get_tracer().health(),
        "llm": {
            "configured": provider.settings.configured,
            "api_version": provider.settings.azure_openai_api_version,
            "roles": provider.describe(),
        },
        "policy": {
            "max_retries": settings.max_retries,
            "run_budget_usd": settings.run_budget_usd,
            "patch_max_failed_checks": settings.patch_max_failed_checks,
            "helper_language": settings.helper_language,
        },
    }


@router.post("/system/llm-check", tags=["system"])
async def llm_check(request: Request) -> dict[str, Any]:
    """Make three tiny calls per deployment (chat, structured output, tools) to verify Azure."""
    provider: LLMProvider = request.app.state.llm
    if not provider.settings.configured:
        raise HTTPException(status_code=400, detail="Azure OpenAI is not configured in .env")
    return {"results": await run_doctor(provider)}


def create_app(
    settings: OrchestratorSettings | None = None,
    clients: Clients | None = None,
    llm: LLMProvider | None = None,
    redis: Any = None,
) -> FastAPI:
    settings = settings or OrchestratorSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.clients = clients or build_clients(settings)
        app.state.llm = llm or LLMProvider()
        app.state.queue = JobQueue(app.state.redis, settings.job_stream, settings.job_group)
        await app.state.queue.ensure_group()
        yield
        if clients is None:
            await app.state.clients.aclose()

    app = create_service_app(
        name="orchestrator",
        version=__version__,
        settings=settings,
        description="Public API for lesson runs: queue a run, watch the agentic loop live (SSE), "
        "cancel/resume, export the lesson and its rejection log, and check system health.",
        lifespan=lifespan,
        redis_client=redis,
    )
    app.include_router(router)
    return app


app = create_app()
