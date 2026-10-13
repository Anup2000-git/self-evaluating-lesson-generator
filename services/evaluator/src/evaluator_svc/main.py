"""Evaluator service API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request

from evaluator_svc import __version__
from evaluator_svc.clients import KnowledgeClient, MemoryClient, RubricProvider
from evaluator_svc.engine import EvaluationEngine
from evaluator_svc.faults import (
    FaultApplied,
    FaultApplyRequest,
    FaultInfo,
    apply_fault,
    list_faults,
)
from evaluator_svc.settings import EvaluatorSettings
from lessongen_common.http import ServiceClient
from lessongen_common.llm import LLMProvider
from lessongen_common.schemas import EvaluateRequest, EvaluationReport, Lesson
from lessongen_common.service import create_service_app
from lessongen_common.testing.samples import sample_lesson

router = APIRouter(prefix="/v1")


@router.post("/evaluations", response_model=EvaluationReport, tags=["evaluation"])
async def evaluate(body: EvaluateRequest, request: Request) -> EvaluationReport:
    """Run every rubric check on a lesson. All must pass for the lesson to ship."""
    engine: EvaluationEngine = request.app.state.engine
    return await engine.evaluate(body)


@router.get("/faults", response_model=list[FaultInfo], tags=["evaluator lab"])
async def faults() -> list[FaultInfo]:
    """Deliberate-error presets used to demonstrate (and test) that the evaluator catches mistakes."""
    return list_faults()


@router.post("/faults/apply", response_model=FaultApplied, tags=["evaluator lab"])
async def inject_fault(body: FaultApplyRequest) -> FaultApplied:
    return apply_fault(body.lesson, body.fault_id)


@router.get("/faults/reference-lesson", response_model=Lesson, tags=["evaluator lab"])
async def reference_lesson() -> Lesson:
    """A reviewed, hand-written RAG lesson that passes every deterministic check - the Lab's
    default starting point before any run has shipped."""
    return sample_lesson()


def create_app(
    settings: EvaluatorSettings | None = None,
    llm: LLMProvider | None = None,
    engine: EvaluationEngine | None = None,
) -> FastAPI:
    settings = settings or EvaluatorSettings()
    provider = llm or LLMProvider()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        knowledge_http = ServiceClient(
            "knowledge",
            settings.knowledge_url,
            timeout=settings.knowledge_timeout_seconds,
            retries=settings.http_retries,
        )
        memory_http = ServiceClient(
            "memory",
            settings.memory_url,
            timeout=settings.http_timeout_seconds,
            retries=settings.http_retries,
        )
        app.state.engine = engine or EvaluationEngine(
            provider,
            KnowledgeClient(knowledge_http),
            RubricProvider(MemoryClient(memory_http), settings.rubric_cache_seconds),
            settings,
        )
        app.state.http = (knowledge_http, memory_http)
        yield
        for client in app.state.http:
            await client.aclose()

    app = create_service_app(
        name="evaluator",
        version=__version__,
        settings=settings,
        description="Hard pass/fail rubric engine: deterministic checks, single-check LLM judges with "
        "verified evidence and vote confirmation, a ReAct fact-checker over the knowledge base, a "
        "simulated learner, and deliberate-error presets.",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
