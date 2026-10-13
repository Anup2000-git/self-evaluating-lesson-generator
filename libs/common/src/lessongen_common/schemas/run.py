"""Run lifecycle contracts (one run = one generate -> evaluate -> regenerate loop)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from lessongen_common.schemas.evaluation import EvaluationReport
from lessongen_common.schemas.lesson import Lesson, LessonPlan, RevisionNote
from lessongen_common.schemas.usage import Usage


class RunMode(StrEnum):
    GENERATE = "generate"
    EVALUATE_ONLY = "evaluate_only"
    REPAIR = "repair"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SHIPPED = "shipped"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    EVALUATED = "evaluated"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {
        RunStatus.SHIPPED,
        RunStatus.NEEDS_HUMAN_REVIEW,
        RunStatus.EVALUATED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)


class RunRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    mode: RunMode = RunMode.GENERATE
    max_retries: int = Field(default=2, ge=0, le=2)
    helper_language: str = Field(default="Hindi", min_length=2, max_length=40)
    initial_lesson: Lesson | None = None
    fault_id: str | None = Field(default=None, max_length=60)
    source_run_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _lesson_matches_mode(self) -> RunRequest:
        if self.mode == RunMode.GENERATE and self.initial_lesson is not None:
            raise ValueError("initial_lesson is only allowed for evaluate_only / repair runs")
        if self.mode != RunMode.GENERATE and self.initial_lesson is None:
            raise ValueError(f"mode '{self.mode}' needs an initial_lesson")
        return self


class AttemptKind(StrEnum):
    INITIAL = "initial"  # first draft written by the writer agent
    PATCH = "patch"  # targeted fix of the failing parts
    REWRITE = "rewrite"  # fresh draft with the feedback (used when too much failed)
    PROVIDED = "provided"  # lesson supplied by a human / the Evaluator Lab


class SectionDiff(BaseModel):
    kind: str
    heading: str
    change: Literal["added", "removed", "modified", "unchanged"]
    words_before: int
    words_after: int


class AttemptRecord(BaseModel):
    attempt_no: int
    kind: AttemptKind
    lesson: Lesson
    evaluation: EvaluationReport
    revision_notes: list[RevisionNote] = Field(default_factory=list)
    diff: list[SectionDiff] = Field(default_factory=list)
    strategy_reason: str = ""
    generation_usage: Usage = Field(default_factory=Usage)
    created_at: datetime


class RunRecord(BaseModel):
    id: str
    topic: str
    topic_id: str | None = None
    mode: RunMode
    status: RunStatus
    status_reason: str | None = None
    max_retries: int
    helper_language: str
    attempts_count: int = 0
    final_attempt_no: int | None = None
    rubric_version: int | None = None
    guideline_ids_applied: list[str] = Field(default_factory=list)
    plan: LessonPlan | None = None
    usage: Usage = Field(default_factory=Usage)
    fault_id: str | None = None
    source_run_id: str | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunDetail(RunRecord):
    attempts: list[AttemptRecord] = Field(default_factory=list)

    def final_attempt(self) -> AttemptRecord | None:
        if self.final_attempt_no is None:
            return None
        return next((a for a in self.attempts if a.attempt_no == self.final_attempt_no), None)


class RunCreate(BaseModel):
    """Payload the orchestrator sends to the memory service when a run is queued."""

    id: str
    topic: str
    topic_id: str | None
    mode: RunMode
    max_retries: int
    helper_language: str
    fault_id: str | None = None
    source_run_id: str | None = None


class RunUpdate(BaseModel):
    status: RunStatus | None = None
    status_reason: str | None = None
    topic_id: str | None = None
    final_attempt_no: int | None = None
    rubric_version: int | None = None
    guideline_ids_applied: list[str] | None = None
    plan: LessonPlan | None = None
    usage: Usage | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunList(BaseModel):
    items: list[RunRecord]
    total: int
