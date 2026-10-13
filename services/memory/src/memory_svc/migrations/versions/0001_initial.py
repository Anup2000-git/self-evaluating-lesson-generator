"""Initial schema: runs, attempts, guidelines, feedback, rubric versions and proposals.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("topic", sa.String(200), nullable=False),
        sa.Column("topic_id", sa.String(64), index=True),
        sa.Column("mode", sa.String(20), nullable=False, index=True),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("status_reason", sa.Text()),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("helper_language", sa.String(40), nullable=False),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final_attempt_no", sa.Integer()),
        sa.Column("rubric_version", sa.Integer()),
        sa.Column("guideline_ids_applied", JSONType, nullable=False),
        sa.Column("plan", JSONType),
        sa.Column("usage", JSONType, nullable=False),
        sa.Column("fault_id", sa.String(60)),
        sa.Column("source_run_id", sa.String(64)),
        sa.Column("error", sa.Text()),
        sa.Column("consolidated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", TS, nullable=False, index=True),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(40),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failed_check_ids", JSONType, nullable=False),
        sa.Column("lesson", JSONType, nullable=False),
        sa.Column("evaluation", JSONType, nullable=False),
        sa.Column("revision_notes", JSONType, nullable=False),
        sa.Column("diff", JSONType, nullable=False),
        sa.Column("strategy_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("generation_usage", JSONType, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("run_id", "attempt_no", name="uq_attempt_run_no"),
    )
    op.create_table(
        "guidelines",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("topic_id", sa.String(64), index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("check_ids", JSONType, nullable=False),
        sa.Column("target", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("times_applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_helped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("times_missed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_from_run", sa.String(40)),
        sa.Column("history", JSONType, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("run_id", sa.String(40), nullable=False, index=True),
        sa.Column("rating", sa.String(10)),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("check_overrides", JSONType, nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "rubric_versions",
        sa.Column("version", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("rubric", JSONType, nullable=False),
        sa.Column("change_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "rubric_proposals",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("check_id", sa.String(20)),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("proposed_change", JSONType, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence", JSONType, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("decided_at", TS),
        sa.Column("resulting_version", sa.Integer()),
    )


def downgrade() -> None:
    for table in (
        "rubric_proposals",
        "rubric_versions",
        "feedback",
        "guidelines",
        "attempts",
        "runs",
    ):
        op.drop_table(table)
