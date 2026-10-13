"""Long-term memory contracts: guidelines (learned prompt rules), feedback, rubric evolution."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from lessongen_common.schemas.evaluation import Verdict
from lessongen_common.schemas.rubric import Rubric
from lessongen_common.schemas.usage import Usage


class GuidelineStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class GuidelineOrigin(StrEnum):
    FAILURE = "failure"
    FEEDBACK = "feedback"
    HUMAN = "human"


class GuidelineTarget(StrEnum):
    PLANNER = "planner"
    WRITER = "writer"
    BOTH = "both"


class GuidelineHistoryEntry(BaseModel):
    version: int
    text: str
    reason: str
    at: datetime


class Guideline(BaseModel):
    id: str
    topic_id: str | None
    text: str
    check_ids: list[str]
    target: GuidelineTarget
    status: GuidelineStatus
    origin: GuidelineOrigin
    version: int
    times_applied: int
    times_helped: int
    times_missed: int
    created_from_run: str | None
    history: list[GuidelineHistoryEntry] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @property
    def effectiveness(self) -> float | None:
        judged = self.times_helped + self.times_missed
        return None if judged == 0 else round(self.times_helped / judged, 3)


class GuidelineUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=400)
    status: GuidelineStatus | None = None
    reason: str = Field(default="edited by a human", max_length=300)


class CheckFailureStat(BaseModel):
    check_id: str
    runs: int
    first_attempt_failures: int
    any_attempt_failures: int
    first_attempt_fail_rate: float


class MemoryContext(BaseModel):
    """What a new run remembers from previous runs (injected into planner/writer prompts)."""

    topic_id: str
    guidelines: list[Guideline] = Field(default_factory=list)
    frequent_failures: list[CheckFailureStat] = Field(default_factory=list)
    human_notes: list[str] = Field(default_factory=list)


class CheckOverride(BaseModel):
    check_id: str
    human_verdict: Verdict
    note: str = Field(default="", max_length=1000)


class FeedbackCreate(BaseModel):
    run_id: str
    rating: Literal["up", "down"] | None = None
    comment: str = Field(default="", max_length=2000)
    check_overrides: list[CheckOverride] = Field(default_factory=list)


class Feedback(FeedbackCreate):
    id: str
    processed: bool
    created_at: datetime


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProposalKind(StrEnum):
    CLARIFY_CHECK = "clarify_check"
    PROMPT_CHANGE = "prompt_change"


class RubricProposal(BaseModel):
    id: str
    check_id: str | None
    kind: ProposalKind
    title: str
    proposed_change: dict[str, Any]
    rationale: str
    evidence: list[str]
    source: Literal["consolidation", "feedback", "escalation"]
    status: ProposalStatus
    created_at: datetime
    decided_at: datetime | None = None
    resulting_version: int | None = None


class ProposalDecision(BaseModel):
    note: str = Field(default="", max_length=500)


class RubricVersionInfo(BaseModel):
    version: int
    status: Literal["active", "superseded"]
    change_note: str
    created_by: str
    created_at: datetime
    rubric: Rubric


class EffectivenessUpdate(BaseModel):
    guideline_id: str
    check_ids: list[str]
    outcome: Literal["helped", "missed"]


class ConsolidationRequest(BaseModel):
    run_id: str | None = Field(
        default=None, description="Run to learn from; omit to only process pending feedback."
    )


class ConsolidationResult(BaseModel):
    run_id: str | None
    added: list[Guideline] = Field(default_factory=list)
    sharpened: list[Guideline] = Field(default_factory=list)
    retired: list[Guideline] = Field(default_factory=list)
    proposals: list[RubricProposal] = Field(default_factory=list)
    effectiveness: list[EffectivenessUpdate] = Field(default_factory=list)
    feedback_processed: int = 0
    usage: Usage = Field(default_factory=Usage)
    summary: str = ""


class RunTrendPoint(BaseModel):
    run_id: str
    created_at: datetime
    status: str
    attempts: int
    first_attempt_passed: bool
    first_attempt_failed_checks: int
    guidelines_applied: int
    cost_usd: float


class StatsResponse(BaseModel):
    runs_total: int
    runs_shipped: int
    runs_needs_review: int
    first_pass_rate: float | None
    avg_attempts: float | None
    avg_cost_usd: float | None
    total_cost_usd: float
    guidelines_active: int
    guidelines_retired: int
    pending_proposals: int
    trend: list[RunTrendPoint]
    checks: list[CheckFailureStat]
