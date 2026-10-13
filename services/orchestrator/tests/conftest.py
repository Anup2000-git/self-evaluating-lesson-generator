"""In-memory fakes for the four downstream services, plus a recording event bus."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from langgraph.checkpoint.memory import InMemorySaver

from lessongen_common.events import EventBus, configure_event_bus
from lessongen_common.schemas import (
    AttemptRecord,
    ConsolidationResult,
    EvaluationReport,
    Guideline,
    GuidelineOrigin,
    GuidelineStatus,
    GuidelineTarget,
    LessonResponse,
    MemoryContext,
    PlanResponse,
    RevisionNote,
    RunCreate,
    RunDetail,
    RunList,
    RunMode,
    RunRecord,
    RunStatus,
    RunUpdate,
    TopicPackSummary,
    TopicResolution,
    Usage,
)
from lessongen_common.testing import sample_lesson, sample_plan, sample_report
from orchestrator_svc.graph.pipeline import Pipeline
from orchestrator_svc.jobs import Job
from orchestrator_svc.settings import OrchestratorSettings
from orchestrator_svc.wiring import Clients


def now() -> datetime:
    return datetime.now(UTC)


class FakeMemory:
    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}
        self.attempts: dict[str, dict[int, AttemptRecord]] = {}
        self.updates: list[tuple[str, RunUpdate]] = []
        self.consolidated: list[str | None] = []
        g = Guideline(
            id="G-1",
            topic_id="rag",
            text="Explain embeddings first.",
            check_ids=["JAR-2"],
            target=GuidelineTarget.WRITER,
            status=GuidelineStatus.ACTIVE,
            origin=GuidelineOrigin.FAILURE,
            version=1,
            times_applied=0,
            times_helped=0,
            times_missed=0,
            created_from_run=None,
            created_at=now(),
            updated_at=now(),
        )
        self.context_result = MemoryContext(topic_id="rag", guidelines=[g])

    def ensure(self, run_id: str, mode: RunMode = RunMode.GENERATE) -> None:
        self.runs.setdefault(
            run_id,
            RunRecord(
                id=run_id,
                topic="Introduction to RAG",
                topic_id="rag",
                mode=mode,
                status=RunStatus.QUEUED,
                max_retries=2,
                helper_language="Hindi",
                created_at=now(),
            ),
        )

    async def context(self, topic_id: str) -> MemoryContext:
        return self.context_result

    async def create_run(self, data: RunCreate) -> RunRecord:
        record = RunRecord(
            id=data.id,
            topic=data.topic,
            topic_id=data.topic_id,
            mode=data.mode,
            status=RunStatus.QUEUED,
            max_retries=data.max_retries,
            helper_language=data.helper_language,
            created_at=now(),
        )
        self.runs[data.id] = record
        return record

    async def update_run(self, run_id: str, patch: RunUpdate) -> RunRecord:
        self.ensure(run_id)
        self.updates.append((run_id, patch))
        values = {f: getattr(patch, f) for f in patch.model_fields_set}
        self.runs[run_id] = self.runs[run_id].model_copy(update=values)
        return self.runs[run_id]

    async def get_run(self, run_id: str) -> RunDetail:
        if run_id not in self.runs:
            from lessongen_common.errors import ServiceError

            raise ServiceError("memory", 404, f"run '{run_id}' not found")
        attempts = sorted(self.attempts.get(run_id, {}).values(), key=lambda a: a.attempt_no)
        return RunDetail(**self.runs[run_id].model_dump(), attempts=attempts)

    async def list_runs(self, **params: Any) -> RunList:
        return RunList(items=list(self.runs.values()), total=len(self.runs))

    async def save_attempt(self, run_id: str, attempt: AttemptRecord) -> AttemptRecord:
        self.attempts.setdefault(run_id, {})[attempt.attempt_no] = attempt
        return attempt

    async def consolidate(self, run_id: str | None) -> ConsolidationResult:
        self.consolidated.append(run_id)
        return ConsolidationResult(
            run_id=run_id, summary="1 new guideline(s)", usage=Usage(llm_calls=1, cost_usd=0.01)
        )


class FakeGenerator:
    def __init__(self, cost: float = 0.1) -> None:
        self.calls: list[Any] = []
        self.cost = cost

    def _usage(self) -> Usage:
        return Usage(llm_calls=2, input_tokens=100, output_tokens=50, cost_usd=self.cost)

    async def plan(self, request: Any) -> PlanResponse:
        self.calls.append("plan")
        return PlanResponse(plan=sample_plan(), usage=self._usage(), prompt_version="planner@test")

    async def write(self, request: Any) -> LessonResponse:
        self.calls.append("write")
        assert request.context.memory.guidelines, "recalled memory must reach the writer"
        return LessonResponse(
            lesson=sample_lesson(), usage=self._usage(), agent_steps=4, prompt_version="writer@test"
        )

    async def revise(self, request: Any) -> LessonResponse:
        ids = [r.check_id for r in request.failed]
        self.calls.append(("revise", request.strategy.value, ids, request.plan is not None))
        lesson = request.previous_lesson.model_copy(deep=True)
        lesson.sections[3].body_markdown += f"\n\nRevised to fix {', '.join(ids)}."
        return LessonResponse(
            lesson=lesson,
            revision_notes=[RevisionNote(check_id=c, change=f"fixed {c}") for c in ids],
            usage=self._usage(),
            agent_steps=2,
            prompt_version="writer@test",
        )


class FakeEvaluator:
    """Returns one scripted report per call: a list of failing check ids, or an exception."""

    def __init__(self, script: list[Any], cost: float = 0.05) -> None:
        self.script = script
        self.calls = 0
        self.cost = cost

    async def evaluate(self, request: Any) -> EvaluationReport:
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        errors: set[str] = set()
        if isinstance(item, dict):
            errors = set(item.get("errors", []))
            item = item["failed"]
        report = sample_report(item)
        for result in report.results:
            if result.check_id in errors:
                result.details = {"error": "timeout"}
        report.error_check_ids = sorted(errors)
        report.usage = Usage(llm_calls=20, cost_usd=self.cost)
        return report


class FakeKnowledge:
    async def resolve(self, text: str) -> TopicResolution | None:
        return (
            TopicResolution(topic_id="rag", title="Introduction to RAG", confidence=1.0)
            if "rag" in text.lower()
            else None
        )

    async def list_topics(self) -> list[TopicPackSummary]:
        return [
            TopicPackSummary(
                id="rag",
                title="Introduction to RAG",
                aliases=["rag"],
                summary="s",
                version="1",
                document_count=11,
                chunk_count=60,
            )
        ]


class FakePing:
    async def ping(self, path: str = "/readyz") -> dict[str, Any]:
        return {"ok": True, "status": 200}

    async def aclose(self) -> None:
        return None


class RecordingBus(EventBus):
    def __init__(self, redis: Any = None) -> None:
        super().__init__(redis, "orchestrator")
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(
        self, run_id: str, type: str, data: dict | None = None, **kwargs: Any
    ) -> str | None:  # type: ignore[override]
        self.events.append((run_id, str(type), data or {}))
        return await super().publish(run_id, type, data, **kwargs)

    def types(self, run_id: str | None = None) -> list[str]:
        return [t for r, t, _ in self.events if run_id is None or r == run_id]


@pytest.fixture
def settings() -> OrchestratorSettings:
    return OrchestratorSettings(  # type: ignore[call-arg]
        _env_file=None,
        use_checkpointer=False,
        events_enabled=False,
        log_json=False,
        run_budget_usd=5.0,
    )


@pytest.fixture
def bus() -> Any:
    recording = RecordingBus()
    configure_event_bus(recording)
    yield recording
    configure_event_bus(None)


@pytest.fixture
def fakes() -> dict[str, Any]:
    return {"memory": FakeMemory(), "generator": FakeGenerator()}


@pytest.fixture
def make_pipeline(settings: OrchestratorSettings, fakes: dict[str, Any]):
    def build(
        evaluator: FakeEvaluator, *, cancelled: set[str] | None = None, budget: float | None = None
    ) -> tuple[Any, Pipeline]:
        if budget is not None:
            settings.run_budget_usd = budget

        async def is_cancelled(run_id: str) -> bool:
            return run_id in (cancelled or set())

        pipeline = Pipeline(
            memory=fakes["memory"],
            generator=fakes["generator"],
            evaluator=evaluator,
            settings=settings,
            is_cancelled=is_cancelled,
        )
        return pipeline.build(InMemorySaver()), pipeline

    return build


def make_job(
    run_id: str = "run_t",
    mode: RunMode = RunMode.GENERATE,
    *,
    lesson: bool = False,
    max_retries: int = 2,
) -> Job:
    return Job(
        run_id=run_id,
        mode=mode,
        topic="Introduction to RAG",
        topic_id="rag",
        topic_title="Introduction to RAG",
        helper_language="Hindi",
        max_retries=max_retries,
        initial_lesson=sample_lesson() if lesson else None,
    )


@pytest.fixture
def job_factory():
    return make_job


@pytest.fixture
def fake_clients(fakes: dict[str, Any]) -> Clients:
    return Clients(
        knowledge=FakeKnowledge(),  # type: ignore[arg-type]
        memory=fakes["memory"],
        generator=fakes["generator"],
        evaluator=FakeEvaluator([[]]),  # type: ignore[arg-type]
        http={
            "knowledge": FakePing(),
            "memory": FakePing(),
            "generator": FakePing(),
            "evaluator": FakePing(),
        },  # type: ignore[dict-item]
    )


@pytest.fixture
def fake_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis()


@pytest.fixture
def evaluator_factory():
    return FakeEvaluator
