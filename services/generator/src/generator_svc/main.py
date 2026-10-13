"""Generator service API (internal - only the orchestrator calls it)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request

from generator_svc import __version__
from generator_svc.planner import Planner
from generator_svc.settings import GeneratorSettings
from generator_svc.writer import Writer
from lessongen_common.clients import KnowledgeClient, MemoryClient, RubricProvider
from lessongen_common.http import ServiceClient
from lessongen_common.llm import LLMProvider
from lessongen_common.schemas import (
    LessonResponse,
    PlanRequest,
    PlanResponse,
    ReviseRequest,
    WriteRequest,
)
from lessongen_common.service import create_service_app

router = APIRouter(prefix="/v1")


@router.post("/plans", response_model=PlanResponse, tags=["generation"])
async def create_plan(body: PlanRequest, request: Request) -> PlanResponse:
    """Outline the lesson: objectives, sections in teaching order, analogy, worked example."""
    planner: Planner = request.app.state.planner
    return await planner.plan(body)


@router.post("/lessons", response_model=LessonResponse, tags=["generation"])
async def write_lesson(body: WriteRequest, request: Request) -> LessonResponse:
    """Run the ReAct writer to produce a complete lesson from the plan."""
    writer: Writer = request.app.state.writer
    return await writer.write(body)


@router.post("/lessons/revisions", response_model=LessonResponse, tags=["generation"])
async def revise_lesson(body: ReviseRequest, request: Request) -> LessonResponse:
    """Revise a rejected lesson: fix every failed check without breaking the passed ones."""
    writer: Writer = request.app.state.writer
    return await writer.revise(body)


def create_app(
    settings: GeneratorSettings | None = None,
    llm: LLMProvider | None = None,
    knowledge: KnowledgeClient | None = None,
    rubrics: RubricProvider | None = None,
) -> FastAPI:
    settings = settings or GeneratorSettings()
    provider = llm or LLMProvider()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        clients: list[ServiceClient] = []
        knowledge_client = knowledge
        rubric_provider = rubrics
        if knowledge_client is None:
            http = ServiceClient(
                "knowledge", settings.knowledge_url, timeout=settings.knowledge_timeout_seconds
            )
            clients.append(http)
            knowledge_client = KnowledgeClient(http)
        if rubric_provider is None:
            http = ServiceClient(
                "memory", settings.memory_url, timeout=settings.http_timeout_seconds
            )
            clients.append(http)
            rubric_provider = RubricProvider(MemoryClient(http), settings.rubric_cache_seconds)
        app.state.planner = Planner(provider, knowledge_client, rubric_provider, settings)
        app.state.writer = Writer(provider, knowledge_client, rubric_provider, settings)
        yield
        for client in clients:
            await client.aclose()

    app = create_service_app(
        name="generator",
        version=__version__,
        settings=settings,
        description="Lesson planner and ReAct writer agent. Internal service called by the orchestrator.",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
