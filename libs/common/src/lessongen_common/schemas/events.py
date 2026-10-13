"""Progress events every service publishes to the run's Redis stream (rendered live in the UI)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    MEMORY_RECALLED = "memory.recalled"
    PLAN_CREATED = "plan.created"
    AGENT_THOUGHT = "agent.thought"
    AGENT_TOOL_CALL = "agent.tool_call"
    AGENT_TOOL_RESULT = "agent.tool_result"
    AGENT_SUBMITTED = "agent.submitted"
    CHECK_COMPLETED = "check.completed"
    EVALUATION_COMPLETED = "evaluation.completed"
    ATTEMPT_REJECTED = "attempt.rejected"
    REVISION_COMPLETED = "revision.completed"
    MEMORY_CONSOLIDATED = "memory.consolidated"
    LOG = "log"


TERMINAL_EVENT_TYPES = frozenset(
    {EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_CANCELLED}
)


class Event(BaseModel):
    id: str | None = Field(default=None, description="Redis stream entry id (set on read).")
    run_id: str
    ts: datetime
    service: str
    type: str
    node: str | None = None
    attempt: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
