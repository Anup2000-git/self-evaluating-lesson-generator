"""Typed clients for every microservice (the system's internal SDK).

Each wraps a resilient ``ServiceClient`` and speaks only in the shared Pydantic contracts,
so a contract change is caught by the type checker and tests, not in production.
"""

from __future__ import annotations

import time
from typing import Any

from lessongen_common.errors import ServiceError
from lessongen_common.http import ServiceClient
from lessongen_common.logs import get_logger
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import (
    AttemptRecord,
    ConsolidationResult,
    EvaluateRequest,
    EvaluationReport,
    GlossaryItem,
    GlossaryLookupResponse,
    LessonResponse,
    MemoryContext,
    PlanRequest,
    PlanResponse,
    ReviseRequest,
    Rubric,
    RubricVersionInfo,
    RunCreate,
    RunDetail,
    RunList,
    RunRecord,
    RunUpdate,
    SearchResponse,
    TopicPack,
    TopicPackSummary,
    TopicResolution,
    WriteRequest,
)

log = get_logger(__name__)


class KnowledgeClient:
    def __init__(self, http: ServiceClient) -> None:
        self.http = http

    async def list_topics(self) -> list[TopicPackSummary]:
        return [TopicPackSummary.model_validate(t) for t in await self.http.get("/v1/topics")]

    async def resolve(self, text: str) -> TopicResolution | None:
        try:
            return TopicResolution.model_validate(
                await self.http.post("/v1/topics/resolve", json={"text": text})
            )
        except ServiceError as exc:
            if exc.status == 404:
                return None
            raise

    async def topic(self, topic_id: str, *, include_assessment: bool = False) -> TopicPack:
        data = await self.http.get(
            f"/v1/topics/{topic_id}", params={"include_assessment": include_assessment}
        )
        return TopicPack.model_validate(data)

    async def search(self, topic_id: str, query: str, k: int = 4) -> SearchResponse:
        data = await self.http.post(
            "/v1/search", json={"topic_id": topic_id, "query": query, "k": k}
        )
        return SearchResponse.model_validate(data)

    async def glossary(self, topic_id: str) -> list[GlossaryItem]:
        return [
            GlossaryItem.model_validate(g)
            for g in await self.http.get(f"/v1/topics/{topic_id}/glossary")
        ]

    async def lookup(self, topic_id: str, terms: list[str]) -> GlossaryLookupResponse:
        data = await self.http.post(f"/v1/topics/{topic_id}/glossary/lookup", json={"terms": terms})
        return GlossaryLookupResponse.model_validate(data)


class MemoryClient:
    def __init__(self, http: ServiceClient, *, consolidation_timeout: float = 180.0) -> None:
        self.http = http
        self.consolidation_timeout = consolidation_timeout

    async def create_run(self, data: RunCreate) -> RunRecord:
        return RunRecord.model_validate(
            await self.http.post("/v1/runs", json=data.model_dump(mode="json"))
        )

    async def update_run(self, run_id: str, patch: RunUpdate) -> RunRecord:
        body = patch.model_dump(mode="json", exclude_unset=True)
        return RunRecord.model_validate(await self.http.patch(f"/v1/runs/{run_id}", json=body))

    async def get_run(self, run_id: str) -> RunDetail:
        return RunDetail.model_validate(await self.http.get(f"/v1/runs/{run_id}"))

    async def list_runs(self, **params: Any) -> RunList:
        clean = {k: v for k, v in params.items() if v is not None}
        return RunList.model_validate(await self.http.get("/v1/runs", params=clean))

    async def save_attempt(self, run_id: str, attempt: AttemptRecord) -> AttemptRecord:
        data = await self.http.put(
            f"/v1/runs/{run_id}/attempts/{attempt.attempt_no}", json=attempt.model_dump(mode="json")
        )
        return AttemptRecord.model_validate(data)

    async def context(self, topic_id: str) -> MemoryContext:
        return MemoryContext.model_validate(
            await self.http.get("/v1/context", params={"topic_id": topic_id})
        )

    async def consolidate(self, run_id: str | None) -> ConsolidationResult:
        data = await self.http.post(
            "/v1/consolidations", json={"run_id": run_id}, timeout=self.consolidation_timeout
        )
        return ConsolidationResult.model_validate(data)

    async def active_rubric(self) -> RubricVersionInfo:
        return RubricVersionInfo.model_validate(await self.http.get("/v1/rubric/active"))

    async def rubric_version(self, version: int) -> RubricVersionInfo:
        return RubricVersionInfo.model_validate(
            await self.http.get(f"/v1/rubric/versions/{version}")
        )


class RubricProvider:
    """Active rubric with a short cache; falls back to the seed rubric if memory is down."""

    def __init__(self, memory: MemoryClient, cache_seconds: float = 30.0) -> None:
        self.memory = memory
        self.cache_seconds = cache_seconds
        self._active: tuple[float, Rubric] | None = None
        self._versions: dict[int, Rubric] = {}

    async def get(self, version: int | None = None) -> Rubric:
        if version is not None:
            if version not in self._versions:
                self._versions[version] = (await self.memory.rubric_version(version)).rubric
            return self._versions[version]
        now = time.monotonic()
        if self._active and now - self._active[0] < self.cache_seconds:
            return self._active[1]
        try:
            rubric = (await self.memory.active_rubric()).rubric
        except Exception as exc:
            log.warning("rubric_fallback_to_seed", error=str(exc))
            rubric = load_seed_rubric()
        self._active = (now, rubric)
        return rubric


class GeneratorClient:
    def __init__(self, http: ServiceClient, *, timeout: float = 600.0) -> None:
        self.http = http
        self.timeout = timeout

    async def plan(self, request: PlanRequest) -> PlanResponse:
        data = await self.http.post(
            "/v1/plans", json=request.model_dump(mode="json"), timeout=self.timeout
        )
        return PlanResponse.model_validate(data)

    async def write(self, request: WriteRequest) -> LessonResponse:
        data = await self.http.post(
            "/v1/lessons", json=request.model_dump(mode="json"), timeout=self.timeout
        )
        return LessonResponse.model_validate(data)

    async def revise(self, request: ReviseRequest) -> LessonResponse:
        data = await self.http.post(
            "/v1/lessons/revisions", json=request.model_dump(mode="json"), timeout=self.timeout
        )
        return LessonResponse.model_validate(data)


class EvaluatorClient:
    def __init__(self, http: ServiceClient, *, timeout: float = 600.0) -> None:
        self.http = http
        self.timeout = timeout

    async def evaluate(self, request: EvaluateRequest) -> EvaluationReport:
        data = await self.http.post(
            "/v1/evaluations", json=request.model_dump(mode="json"), timeout=self.timeout
        )
        return EvaluationReport.model_validate(data)
