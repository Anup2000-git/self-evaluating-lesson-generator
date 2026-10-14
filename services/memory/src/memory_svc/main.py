"""Memory service API: runs & rejection logs, memory context, guidelines, feedback, rubric, stats."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Query, Request, status

from lessongen_common.llm import LLMProvider
from lessongen_common.schemas import (
    AttemptRecord,
    ConsolidationRequest,
    ConsolidationResult,
    Feedback,
    FeedbackCreate,
    Guideline,
    GuidelineUpdate,
    MemoryContext,
    ProposalDecision,
    RubricProposal,
    RubricVersionInfo,
    RunCreate,
    RunDetail,
    RunList,
    RunRecord,
    RunUpdate,
    StatsResponse,
)
from lessongen_common.service import create_service_app
from lessongen_common.tracing import get_tracer
from memory_svc import __version__
from memory_svc.consolidation import Consolidator
from memory_svc.db import make_engine, make_session_factory, ping
from memory_svc.repository import MemoryRepository
from memory_svc.settings import MemorySettings

router = APIRouter(prefix="/v1")


def _repo(request: Request) -> MemoryRepository:
    return request.app.state.repo


# ------------------------------------------------------------------- runs
@router.post("/runs", response_model=RunRecord, status_code=status.HTTP_201_CREATED, tags=["runs"])
async def create_run(body: RunCreate, request: Request) -> RunRecord:
    return await _repo(request).create_run(body)


@router.get("/runs", response_model=RunList, tags=["runs"])
async def list_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    topic_id: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    mode: str | None = None,
) -> RunList:
    return await _repo(request).list_runs(
        limit=limit, offset=offset, topic_id=topic_id, status=status_filter, mode=mode
    )


@router.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"])
async def get_run(run_id: str, request: Request) -> RunDetail:
    return await _repo(request).get_run(run_id)


@router.patch("/runs/{run_id}", response_model=RunRecord, tags=["runs"])
async def update_run(run_id: str, body: RunUpdate, request: Request) -> RunRecord:
    return await _repo(request).update_run(run_id, body)


@router.put("/runs/{run_id}/attempts/{attempt_no}", response_model=AttemptRecord, tags=["runs"])
async def save_attempt(
    run_id: str, attempt_no: int, body: AttemptRecord, request: Request
) -> AttemptRecord:
    if body.attempt_no != attempt_no:
        body = body.model_copy(update={"attempt_no": attempt_no})
    return await _repo(request).save_attempt(run_id, body)


# ----------------------------------------------------------------- memory
@router.get("/context", response_model=MemoryContext, tags=["memory"])
async def memory_context(
    request: Request, topic_id: str = Query(..., min_length=1)
) -> MemoryContext:
    """What a new run should remember: best guidelines, frequent failures, human notes."""
    return await _repo(request).memory_context(topic_id)


@router.get("/guidelines", response_model=list[Guideline], tags=["memory"])
async def list_guidelines(
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
    topic_id: str | None = None,
) -> list[Guideline]:
    return await _repo(request).list_guidelines(status=status_filter, topic_id=topic_id)


@router.patch("/guidelines/{guideline_id}", response_model=Guideline, tags=["memory"])
async def update_guideline(guideline_id: str, body: GuidelineUpdate, request: Request) -> Guideline:
    return await _repo(request).update_guideline(guideline_id, body)


@router.post("/consolidations", response_model=ConsolidationResult, tags=["memory"])
async def consolidate(body: ConsolidationRequest, request: Request) -> ConsolidationResult:
    """Learn from a finished run (and any pending human feedback): the self-evolving step."""
    consolidator: Consolidator = request.app.state.consolidator
    with get_tracer().span(
        "memory.consolidate", as_type="chain", input={"run_id": body.run_id}
    ) as span:
        result = await consolidator.consolidate(body.run_id)
        span.update(output=result.model_dump(mode="json"))
    return result


# --------------------------------------------------------------- feedback
@router.post(
    "/feedback", response_model=Feedback, status_code=status.HTTP_201_CREATED, tags=["feedback"]
)
async def add_feedback(body: FeedbackCreate, request: Request) -> Feedback:
    return await _repo(request).add_feedback(body)


@router.get("/feedback", response_model=list[Feedback], tags=["feedback"])
async def list_feedback(
    request: Request, run_id: str | None = None, processed: bool | None = None
) -> list[Feedback]:
    return await _repo(request).list_feedback(run_id=run_id, processed=processed)


# ----------------------------------------------------------------- rubric
@router.get("/rubric/active", response_model=RubricVersionInfo, tags=["rubric"])
async def active_rubric(request: Request) -> RubricVersionInfo:
    return await _repo(request).active_rubric()


@router.get("/rubric/versions", response_model=list[RubricVersionInfo], tags=["rubric"])
async def rubric_versions(request: Request) -> list[RubricVersionInfo]:
    return await _repo(request).list_rubric_versions()


@router.get("/rubric/versions/{version}", response_model=RubricVersionInfo, tags=["rubric"])
async def rubric_version(version: int, request: Request) -> RubricVersionInfo:
    return await _repo(request).rubric_version(version)


@router.get("/rubric/proposals", response_model=list[RubricProposal], tags=["rubric"])
async def list_proposals(
    request: Request, status_filter: str | None = Query(None, alias="status")
) -> list[RubricProposal]:
    return await _repo(request).list_proposals(status_filter)


@router.post(
    "/rubric/proposals/{proposal_id}/approve", response_model=RubricProposal, tags=["rubric"]
)
async def approve_proposal(
    proposal_id: str, body: ProposalDecision, request: Request
) -> RubricProposal:
    """Human sign-off: a clarification proposal becomes a new rubric version."""
    return await _repo(request).decide_proposal(proposal_id, approve=True, note=body.note)


@router.post(
    "/rubric/proposals/{proposal_id}/reject", response_model=RubricProposal, tags=["rubric"]
)
async def reject_proposal(
    proposal_id: str, body: ProposalDecision, request: Request
) -> RubricProposal:
    return await _repo(request).decide_proposal(proposal_id, approve=False, note=body.note)


# ------------------------------------------------------------------ stats
@router.get("/stats", response_model=StatsResponse, tags=["stats"])
async def stats(request: Request, topic_id: str | None = None) -> StatsResponse:
    return await _repo(request).stats(topic_id)


def create_app(settings: MemorySettings | None = None, llm: LLMProvider | None = None) -> FastAPI:
    settings = settings or MemorySettings()
    engine = make_engine(settings.database_url, settings.db_pool_size)
    repo = MemoryRepository(make_session_factory(engine), settings)
    provider = llm or LLMProvider()

    async def db_ready() -> None:
        await ping(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.repo = repo
        app.state.consolidator = Consolidator(repo, provider, settings)
        yield
        await engine.dispose()

    app = create_service_app(
        name="memory",
        version=__version__,
        settings=settings,
        description="Long-term memory: runs and rejection logs, learned guidelines, human feedback, "
        "versioned rubric with human-approved proposals, and learning statistics.",
        lifespan=lifespan,
        readiness_checks={"database": db_ready},
    )
    app.include_router(router)
    return app


app = create_app()
