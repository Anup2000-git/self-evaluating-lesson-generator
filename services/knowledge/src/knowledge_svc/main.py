"""Knowledge service API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Query, Request

from knowledge_svc import __version__
from knowledge_svc.embeddings import attach_dense_retrievers
from knowledge_svc.packs import PackRegistry
from knowledge_svc.settings import KnowledgeSettings
from lessongen_common.errors import NotFoundError
from lessongen_common.llm import LLMSettings
from lessongen_common.schemas.topic import (
    GlossaryItem,
    GlossaryLookupRequest,
    GlossaryLookupResponse,
    KBDocument,
    SearchRequest,
    SearchResponse,
    TopicPack,
    TopicPackSummary,
    TopicResolution,
    TopicResolveRequest,
)
from lessongen_common.service import create_service_app

router = APIRouter(prefix="/v1", tags=["knowledge"])


def _registry(request: Request) -> PackRegistry:
    return request.app.state.registry


@router.get("/topics", response_model=list[TopicPackSummary], summary="List topic packs")
async def list_topics(request: Request) -> list[TopicPackSummary]:
    return [p.summary() for p in _registry(request).packs.values()]


@router.post("/topics/resolve", response_model=TopicResolution, summary="Map free text to a topic")
async def resolve_topic(body: TopicResolveRequest, request: Request) -> TopicResolution:
    resolution = _registry(request).resolve(body.text)
    if resolution is None:
        available = ", ".join(p.pack.title for p in _registry(request).packs.values())
        raise NotFoundError(
            f"No grounded knowledge pack for '{body.text}'. Available topics: {available}. "
            "Lessons are only generated for topics we can ground and fact-check."
        )
    return resolution


@router.get("/topics/{topic_id}", response_model=TopicPack, summary="Get a topic pack")
async def get_topic(
    topic_id: str,
    request: Request,
    include_assessment: bool = Query(
        default=False,
        description="Include held-out learner questions (evaluator only - never the writer).",
    ),
) -> TopicPack:
    pack = _registry(request).get(topic_id).pack
    return pack if include_assessment else pack.model_copy(update={"learner_questions": []})


@router.get("/topics/{topic_id}/glossary", response_model=list[GlossaryItem])
async def get_glossary(topic_id: str, request: Request) -> list[GlossaryItem]:
    return _registry(request).get(topic_id).glossary


@router.post("/topics/{topic_id}/glossary/lookup", response_model=GlossaryLookupResponse)
async def lookup_glossary(
    topic_id: str, body: GlossaryLookupRequest, request: Request
) -> GlossaryLookupResponse:
    return _registry(request).get(topic_id).lookup(body.terms)


@router.get("/topics/{topic_id}/documents", response_model=list[KBDocument])
async def get_documents(topic_id: str, request: Request) -> list[KBDocument]:
    return _registry(request).get(topic_id).documents


@router.post("/search", response_model=SearchResponse, summary="Search a topic's knowledge base")
async def search(body: SearchRequest, request: Request) -> SearchResponse:
    retriever, hits = await _registry(request).search(body.topic_id, body.query, body.k)
    return SearchResponse(topic_id=body.topic_id, query=body.query, retriever=retriever, hits=hits)


def create_app(
    settings: KnowledgeSettings | None = None, llm_settings: LLMSettings | None = None
) -> FastAPI:
    settings = settings or KnowledgeSettings()
    llm_settings = llm_settings or LLMSettings()
    registry = PackRegistry(settings.packs_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        registry.load()
        await attach_dense_retrievers(registry, llm_settings, settings.embedding_cache_dir)
        app.state.registry = registry
        yield

    app = create_service_app(
        name="knowledge",
        version=__version__,
        settings=settings,
        description="Curated topic packs (ground truth), glossary with helper-language meanings, and search.",
        lifespan=lifespan,
        readiness_checks={"packs": registry.ready},
        use_redis=False,
    )
    app.include_router(router)
    return app


app = create_app()
