"""ORM models. JSON columns become JSONB on Postgres and TEXT on SQLite (tests)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    topic: Mapped[str] = mapped_column(String(200))
    topic_id: Mapped[str | None] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    max_retries: Mapped[int] = mapped_column(Integer)
    helper_language: Mapped[str] = mapped_column(String(40))
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    final_attempt_no: Mapped[int | None] = mapped_column(Integer)
    rubric_version: Mapped[int | None] = mapped_column(Integer)
    guideline_ids_applied: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    fault_id: Mapped[str | None] = mapped_column(String(60))
    source_run_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    consolidated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttemptRow(Base):
    # Attempts are queried explicitly (no ORM relationship) so nothing lazy-loads in async code.
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("run_id", "attempt_no", name="uq_attempt_run_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    passed: Mapped[bool] = mapped_column(Boolean)
    failed_check_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    lesson: Mapped[dict[str, Any]] = mapped_column(JSONType)
    evaluation: Mapped[dict[str, Any]] = mapped_column(JSONType)
    revision_notes: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    diff: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    strategy_reason: Mapped[str] = mapped_column(Text, default="")
    generation_usage: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuidelineRow(Base):
    __tablename__ = "guidelines"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    topic_id: Mapped[str | None] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text)
    check_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    target: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    origin: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    times_helped: Mapped[int] = mapped_column(Integer, default=0)
    times_missed: Mapped[int] = mapped_column(Integer, default=0)
    created_from_run: Mapped[str | None] = mapped_column(String(40))
    history: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeedbackRow(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    rating: Mapped[str | None] = mapped_column(String(10))
    comment: Mapped[str] = mapped_column(Text, default="")
    check_overrides: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RubricVersionRow(Base):
    __tablename__ = "rubric_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    status: Mapped[str] = mapped_column(String(20), index=True)
    rubric: Mapped[dict[str, Any]] = mapped_column(JSONType)
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RubricProposalRow(Base):
    __tablename__ = "rubric_proposals"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    check_id: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(Text)
    proposed_change: Mapped[dict[str, Any]] = mapped_column(JSONType)
    rationale: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resulting_version: Mapped[int | None] = mapped_column(Integer)
