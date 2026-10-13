"""Request/response contracts of the generator service."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from lessongen_common.schemas.evaluation import CheckResult
from lessongen_common.schemas.lesson import Lesson, LessonPlan, RevisionNote
from lessongen_common.schemas.memory import MemoryContext
from lessongen_common.schemas.usage import Usage


class GenerationContext(BaseModel):
    topic_id: str
    topic_title: str
    helper_language: str = "Hindi"
    memory: MemoryContext


class PlanRequest(BaseModel):
    context: GenerationContext


class PlanResponse(BaseModel):
    plan: LessonPlan
    usage: Usage
    prompt_version: str


class WriteRequest(BaseModel):
    context: GenerationContext
    plan: LessonPlan


class ReviseStrategy(StrEnum):
    PATCH = "patch"
    REWRITE = "rewrite"


class ReviseRequest(BaseModel):
    context: GenerationContext
    plan: LessonPlan | None = None
    previous_lesson: Lesson
    failed: list[CheckResult] = Field(min_length=1)
    passed_check_ids: list[str]
    strategy: ReviseStrategy = ReviseStrategy.PATCH


class LessonResponse(BaseModel):
    lesson: Lesson
    revision_notes: list[RevisionNote] = Field(default_factory=list)
    usage: Usage
    agent_steps: int
    prompt_version: str
