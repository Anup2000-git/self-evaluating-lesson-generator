"""Data access for long-term memory. The memory service is the only writer of this database."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lessongen_common.errors import LessongenError, NotFoundError
from lessongen_common.schemas import (
    AttemptRecord,
    CheckFailureStat,
    EffectivenessUpdate,
    Feedback,
    FeedbackCreate,
    Guideline,
    GuidelineHistoryEntry,
    GuidelineOrigin,
    GuidelineStatus,
    GuidelineTarget,
    GuidelineUpdate,
    MemoryContext,
    ProposalKind,
    ProposalStatus,
    Rubric,
    RubricProposal,
    RubricVersionInfo,
    RunCreate,
    RunDetail,
    RunList,
    RunMode,
    RunRecord,
    RunStatus,
    RunTrendPoint,
    RunUpdate,
    StatsResponse,
)
from memory_svc.models import (
    AttemptRow,
    FeedbackRow,
    GuidelineRow,
    RubricProposalRow,
    RubricVersionRow,
    RunRow,
    utcnow,
)
from memory_svc.rubric_evolution import apply_clarification
from memory_svc.settings import MemorySettings

# Runs that reached a quality verdict (errors and cancellations say nothing about quality).
_QUALITY_OUTCOMES = (RunStatus.SHIPPED.value, RunStatus.NEEDS_HUMAN_REVIEW.value)


def short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _effectiveness_rank(g: Guideline) -> tuple[float, int, datetime]:
    smoothed = (g.times_helped + 1) / (g.times_helped + g.times_missed + 2)
    return (smoothed, g.times_applied, g.updated_at)


# --------------------------------------------------------------------- mappers
def run_record(row: RunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        topic=row.topic,
        topic_id=row.topic_id,
        mode=RunMode(row.mode),
        status=RunStatus(row.status),
        status_reason=row.status_reason,
        max_retries=row.max_retries,
        helper_language=row.helper_language,
        attempts_count=row.attempts_count or 0,
        final_attempt_no=row.final_attempt_no,
        rubric_version=row.rubric_version,
        guideline_ids_applied=list(row.guideline_ids_applied or []),
        plan=row.plan,
        usage=row.usage or {},
        fault_id=row.fault_id,
        source_run_id=row.source_run_id,
        error=row.error,
        created_at=_utc(row.created_at),
        started_at=_utc(row.started_at),
        finished_at=_utc(row.finished_at),
    )


def attempt_record(row: AttemptRow) -> AttemptRecord:
    return AttemptRecord(
        attempt_no=row.attempt_no,
        kind=row.kind,
        lesson=row.lesson,
        evaluation=row.evaluation,
        revision_notes=row.revision_notes or [],
        diff=row.diff or [],
        strategy_reason=row.strategy_reason or "",
        generation_usage=row.generation_usage or {},
        created_at=_utc(row.created_at),
    )


def guideline_model(row: GuidelineRow) -> Guideline:
    return Guideline(
        id=row.id,
        topic_id=row.topic_id,
        text=row.text,
        check_ids=list(row.check_ids or []),
        target=GuidelineTarget(row.target),
        status=GuidelineStatus(row.status),
        origin=GuidelineOrigin(row.origin),
        version=row.version,
        times_applied=row.times_applied,
        times_helped=row.times_helped,
        times_missed=row.times_missed,
        created_from_run=row.created_from_run,
        history=[GuidelineHistoryEntry.model_validate(h) for h in row.history or []],
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def feedback_model(row: FeedbackRow) -> Feedback:
    return Feedback(
        id=row.id,
        run_id=row.run_id,
        rating=row.rating,
        comment=row.comment or "",
        check_overrides=row.check_overrides or [],
        processed=row.processed,
        created_at=_utc(row.created_at),
    )


def proposal_model(row: RubricProposalRow) -> RubricProposal:
    return RubricProposal(
        id=row.id,
        check_id=row.check_id,
        kind=ProposalKind(row.kind),
        title=row.title,
        proposed_change=row.proposed_change or {},
        rationale=row.rationale,
        evidence=list(row.evidence or []),
        source=row.source,
        status=ProposalStatus(row.status),
        created_at=_utc(row.created_at),
        decided_at=_utc(row.decided_at),
        resulting_version=row.resulting_version,
    )


def rubric_info(row: RubricVersionRow) -> RubricVersionInfo:
    return RubricVersionInfo(
        version=row.version,
        status=row.status,
        change_note=row.change_note or "",
        created_by=row.created_by,
        created_at=_utc(row.created_at),
        rubric=Rubric.model_validate(row.rubric),
    )


def _history_entry(version: int, text: str, reason: str) -> dict[str, Any]:
    return {"version": version, "text": text, "reason": reason, "at": utcnow().isoformat()}


class MemoryRepository:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], settings: MemorySettings
    ) -> None:
        self.sessions = sessions
        self.settings = settings

    # ------------------------------------------------------------------ runs
    async def create_run(self, data: RunCreate) -> RunRecord:
        async with self.sessions.begin() as s:
            existing = await s.get(RunRow, data.id)
            if existing is not None:  # idempotent: retries of the same request are harmless
                return run_record(existing)
            row = RunRow(
                id=data.id,
                topic=data.topic,
                topic_id=data.topic_id,
                mode=data.mode.value,
                status=RunStatus.QUEUED.value,
                max_retries=data.max_retries,
                helper_language=data.helper_language,
                attempts_count=0,
                guideline_ids_applied=[],
                usage={},
                fault_id=data.fault_id,
                source_run_id=data.source_run_id,
                created_at=utcnow(),
            )
            s.add(row)
            await s.flush()
            return run_record(row)

    async def update_run(self, run_id: str, patch: RunUpdate) -> RunRecord:
        async with self.sessions.begin() as s:
            row = await s.get(RunRow, run_id)
            if row is None:
                raise NotFoundError(f"run '{run_id}' not found")
            for field in patch.model_fields_set:
                value = getattr(patch, field)
                if field in ("plan", "usage") and value is not None:
                    value = value.model_dump(mode="json")
                elif field == "status" and value is not None:
                    value = value.value
                setattr(row, field, value)
            return run_record(row)

    async def get_run(self, run_id: str) -> RunDetail:
        async with self.sessions() as s:
            row = await s.get(RunRow, run_id)
            if row is None:
                raise NotFoundError(f"run '{run_id}' not found")
            attempts = (
                await s.scalars(
                    select(AttemptRow)
                    .where(AttemptRow.run_id == run_id)
                    .order_by(AttemptRow.attempt_no)
                )
            ).all()
            return RunDetail(
                **run_record(row).model_dump(), attempts=[attempt_record(a) for a in attempts]
            )

    async def list_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        topic_id: str | None = None,
        status: str | None = None,
        mode: str | None = None,
    ) -> RunList:
        conditions = []
        if topic_id:
            conditions.append(RunRow.topic_id == topic_id)
        if status:
            conditions.append(RunRow.status == status)
        if mode:
            conditions.append(RunRow.mode == mode)
        async with self.sessions() as s:
            total = await s.scalar(select(func.count()).select_from(RunRow).where(*conditions))
            rows = (
                await s.scalars(
                    select(RunRow)
                    .where(*conditions)
                    .order_by(RunRow.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return RunList(items=[run_record(r) for r in rows], total=total or 0)

    async def save_attempt(self, run_id: str, attempt: AttemptRecord) -> AttemptRecord:
        values = {
            "kind": attempt.kind.value,
            "passed": attempt.evaluation.passed,
            "failed_check_ids": list(attempt.evaluation.failed_check_ids),
            "lesson": attempt.lesson.model_dump(mode="json"),
            "evaluation": attempt.evaluation.model_dump(mode="json"),
            "revision_notes": [n.model_dump(mode="json") for n in attempt.revision_notes],
            "diff": [d.model_dump(mode="json") for d in attempt.diff],
            "strategy_reason": attempt.strategy_reason,
            "generation_usage": attempt.generation_usage.model_dump(mode="json"),
            "created_at": attempt.created_at,
        }
        async with self.sessions.begin() as s:
            run = await s.get(RunRow, run_id)
            if run is None:
                raise NotFoundError(f"run '{run_id}' not found")
            existing = await s.scalar(
                select(AttemptRow).where(
                    AttemptRow.run_id == run_id, AttemptRow.attempt_no == attempt.attempt_no
                )
            )
            if existing is None:
                s.add(AttemptRow(run_id=run_id, attempt_no=attempt.attempt_no, **values))
            else:  # idempotent upsert: a resumed run may re-save the same attempt
                for key, value in values.items():
                    setattr(existing, key, value)
            run.attempts_count = max(run.attempts_count or 0, attempt.attempt_no)
            run.rubric_version = attempt.evaluation.rubric_version
        return attempt

    async def mark_consolidated(self, run_id: str) -> None:
        async with self.sessions.begin() as s:
            row = await s.get(RunRow, run_id)
            if row is not None:
                row.consolidated = True

    # --------------------------------------------------------------- context
    async def _finished_generate_runs(
        self, s: AsyncSession, topic_id: str | None, limit: int | None
    ) -> list[RunRow]:
        stmt = select(RunRow).where(
            RunRow.status.in_(_QUALITY_OUTCOMES),
            RunRow.mode == RunMode.GENERATE.value,
        )
        if topic_id:
            stmt = stmt.where(RunRow.topic_id == topic_id)
        stmt = stmt.order_by(RunRow.created_at.desc())
        if limit:
            stmt = stmt.limit(limit)
        return list((await s.scalars(stmt)).all())

    async def _first_attempts(self, s: AsyncSession, run_ids: list[str]) -> dict[str, AttemptRow]:
        if not run_ids:
            return {}
        rows = (
            await s.scalars(
                select(AttemptRow).where(AttemptRow.run_id.in_(run_ids), AttemptRow.attempt_no == 1)
            )
        ).all()
        return {r.run_id: r for r in rows}

    async def failure_stats(
        self, topic_id: str | None, window: int | None = None
    ) -> list[CheckFailureStat]:
        async with self.sessions() as s:
            runs = await self._finished_generate_runs(s, topic_id, window)
            run_ids = [r.id for r in runs]
            first = await self._first_attempts(s, run_ids)
            all_attempts = (
                (await s.scalars(select(AttemptRow).where(AttemptRow.run_id.in_(run_ids)))).all()
                if run_ids
                else []
            )
        first_fail = Counter(cid for a in first.values() for cid in a.failed_check_ids or [])
        any_fail: Counter[str] = Counter()
        per_run: dict[str, set[str]] = {}
        for a in all_attempts:
            per_run.setdefault(a.run_id, set()).update(a.failed_check_ids or [])
        for ids in per_run.values():
            any_fail.update(ids)
        total = len(runs)
        stats = [
            CheckFailureStat(
                check_id=cid,
                runs=total,
                first_attempt_failures=first_fail.get(cid, 0),
                any_attempt_failures=any_fail.get(cid, 0),
                first_attempt_fail_rate=round(first_fail.get(cid, 0) / total, 3) if total else 0.0,
            )
            for cid in sorted(set(first_fail) | set(any_fail))
        ]
        return sorted(stats, key=lambda x: (-x.first_attempt_fail_rate, x.check_id))

    async def memory_context(self, topic_id: str) -> MemoryContext:
        guidelines = [
            g
            for g in await self.list_guidelines(status=GuidelineStatus.ACTIVE.value)
            if g.topic_id in (None, topic_id)
        ]
        guidelines.sort(key=_effectiveness_rank, reverse=True)
        failures = [
            f
            for f in await self.failure_stats(topic_id, self.settings.context_failure_window_runs)
            if f.first_attempt_fail_rate >= self.settings.context_failure_min_rate
        ][:6]
        async with self.sessions() as s:
            topic_runs = select(RunRow.id).where(RunRow.topic_id == topic_id)
            notes = (
                await s.scalars(
                    select(FeedbackRow)
                    .where(
                        FeedbackRow.processed.is_(False),
                        FeedbackRow.comment != "",
                        FeedbackRow.run_id.in_(topic_runs),
                    )
                    .order_by(FeedbackRow.created_at.desc())
                    .limit(5)
                )
            ).all()
        return MemoryContext(
            topic_id=topic_id,
            guidelines=guidelines[: self.settings.context_guideline_limit],
            frequent_failures=failures,
            human_notes=[n.comment for n in notes],
        )

    # ------------------------------------------------------------ guidelines
    async def list_guidelines(
        self, *, status: str | None = None, topic_id: str | None = None
    ) -> list[Guideline]:
        stmt = select(GuidelineRow)
        if status:
            stmt = stmt.where(GuidelineRow.status == status)
        if topic_id:
            stmt = stmt.where(GuidelineRow.topic_id == topic_id)
        async with self.sessions() as s:
            rows = (await s.scalars(stmt.order_by(GuidelineRow.created_at))).all()
            return [guideline_model(r) for r in rows]

    async def get_guideline(self, guideline_id: str) -> Guideline:
        async with self.sessions() as s:
            row = await s.get(GuidelineRow, guideline_id)
            if row is None:
                raise NotFoundError(f"guideline '{guideline_id}' not found")
            return guideline_model(row)

    async def add_guideline(
        self,
        *,
        topic_id: str | None,
        text: str,
        check_ids: list[str],
        target: GuidelineTarget,
        origin: GuidelineOrigin,
        created_from_run: str | None,
        reason: str,
    ) -> Guideline:
        now = utcnow()
        async with self.sessions.begin() as s:
            row = GuidelineRow(
                id=short_id("G"),
                topic_id=topic_id,
                text=text.strip(),
                check_ids=check_ids,
                target=target.value,
                status=GuidelineStatus.ACTIVE.value,
                origin=origin.value,
                version=1,
                times_applied=0,
                times_helped=0,
                times_missed=0,
                created_from_run=created_from_run,
                history=[_history_entry(1, text.strip(), reason)],
                created_at=now,
                updated_at=now,
            )
            s.add(row)
            await s.flush()
            return guideline_model(row)

    async def update_guideline(self, guideline_id: str, patch: GuidelineUpdate) -> Guideline:
        async with self.sessions.begin() as s:
            row = await s.get(GuidelineRow, guideline_id)
            if row is None:
                raise NotFoundError(f"guideline '{guideline_id}' not found")
            history = list(row.history or [])
            if patch.text is not None and patch.text.strip() != row.text:
                row.version += 1
                row.text = patch.text.strip()
                history.append(_history_entry(row.version, row.text, patch.reason))
            if patch.status is not None and patch.status.value != row.status:
                row.status = patch.status.value
                history.append(
                    _history_entry(row.version, row.text, f"{patch.status.value}: {patch.reason}")
                )
            row.history = history
            row.updated_at = utcnow()
            return guideline_model(row)

    async def record_effectiveness(self, updates: list[EffectivenessUpdate]) -> None:
        if not updates:
            return
        async with self.sessions.begin() as s:
            for update in updates:
                row = await s.get(GuidelineRow, update.guideline_id)
                if row is None:
                    continue
                row.times_applied += 1
                if update.outcome == "helped":
                    row.times_helped += 1
                else:
                    row.times_missed += 1
                row.updated_at = utcnow()

    # -------------------------------------------------------------- feedback
    async def add_feedback(self, data: FeedbackCreate) -> Feedback:
        async with self.sessions.begin() as s:
            if await s.get(RunRow, data.run_id) is None:
                raise NotFoundError(f"run '{data.run_id}' not found")
            row = FeedbackRow(
                id=short_id("F"),
                run_id=data.run_id,
                rating=data.rating,
                comment=data.comment.strip(),
                check_overrides=[o.model_dump(mode="json") for o in data.check_overrides],
                processed=False,
                created_at=utcnow(),
            )
            s.add(row)
            await s.flush()
            return feedback_model(row)

    async def list_feedback(
        self, *, run_id: str | None = None, processed: bool | None = None
    ) -> list[Feedback]:
        stmt = select(FeedbackRow)
        if run_id:
            stmt = stmt.where(FeedbackRow.run_id == run_id)
        if processed is not None:
            stmt = stmt.where(FeedbackRow.processed.is_(processed))
        async with self.sessions() as s:
            rows = (await s.scalars(stmt.order_by(FeedbackRow.created_at.desc()))).all()
            return [feedback_model(r) for r in rows]

    async def mark_feedback_processed(self, ids: list[str]) -> None:
        if not ids:
            return
        async with self.sessions.begin() as s:
            for row in (await s.scalars(select(FeedbackRow).where(FeedbackRow.id.in_(ids)))).all():
                row.processed = True

    # ---------------------------------------------------------------- rubric
    async def seed_rubric(self, rubric: Rubric, created_by: str = "seed") -> bool:
        async with self.sessions.begin() as s:
            if await s.scalar(select(func.count()).select_from(RubricVersionRow)):
                return False
            s.add(
                RubricVersionRow(
                    version=rubric.version,
                    status="active",
                    rubric=rubric.model_dump(mode="json"),
                    change_note="Initial rubric shipped with the code.",
                    created_by=created_by,
                    created_at=utcnow(),
                )
            )
            return True

    async def active_rubric(self) -> RubricVersionInfo:
        async with self.sessions() as s:
            row = await s.scalar(
                select(RubricVersionRow)
                .where(RubricVersionRow.status == "active")
                .order_by(RubricVersionRow.version.desc())
            )
            if row is None:
                raise NotFoundError("no active rubric; run the migrate job to seed rubric v1")
            return rubric_info(row)

    async def rubric_version(self, version: int) -> RubricVersionInfo:
        async with self.sessions() as s:
            row = await s.get(RubricVersionRow, version)
            if row is None:
                raise NotFoundError(f"rubric version {version} not found")
            return rubric_info(row)

    async def list_rubric_versions(self) -> list[RubricVersionInfo]:
        async with self.sessions() as s:
            rows = (
                await s.scalars(select(RubricVersionRow).order_by(RubricVersionRow.version.desc()))
            ).all()
            return [rubric_info(r) for r in rows]

    async def create_proposal(
        self,
        *,
        check_id: str | None,
        kind: ProposalKind,
        title: str,
        proposed_change: dict[str, Any],
        rationale: str,
        evidence: list[str],
        source: str,
    ) -> RubricProposal:
        async with self.sessions.begin() as s:
            row = RubricProposalRow(
                id=short_id("P"),
                check_id=check_id,
                kind=kind.value,
                title=title,
                proposed_change=proposed_change,
                rationale=rationale,
                evidence=evidence,
                source=source,
                status=ProposalStatus.PENDING.value,
                created_at=utcnow(),
            )
            s.add(row)
            await s.flush()
            return proposal_model(row)

    async def list_proposals(self, status: str | None = None) -> list[RubricProposal]:
        stmt = select(RubricProposalRow)
        if status:
            stmt = stmt.where(RubricProposalRow.status == status)
        async with self.sessions() as s:
            rows = (await s.scalars(stmt.order_by(RubricProposalRow.created_at.desc()))).all()
            return [proposal_model(r) for r in rows]

    async def decide_proposal(
        self, proposal_id: str, *, approve: bool, note: str
    ) -> RubricProposal:
        async with self.sessions.begin() as s:
            row = await s.get(RubricProposalRow, proposal_id)
            if row is None:
                raise NotFoundError(f"proposal '{proposal_id}' not found")
            if row.status != ProposalStatus.PENDING.value:
                raise LessongenError(f"proposal '{proposal_id}' was already {row.status}")
            if approve and row.kind == ProposalKind.CLARIFY_CHECK.value:
                active = await s.scalar(
                    select(RubricVersionRow)
                    .where(RubricVersionRow.status == "active")
                    .order_by(RubricVersionRow.version.desc())
                )
                if active is None:
                    raise NotFoundError("no active rubric to change")
                current = Rubric.model_validate(active.rubric)
                updated = apply_clarification(current, row.proposed_change)
                active.status = "superseded"
                s.add(
                    RubricVersionRow(
                        version=updated.version,
                        status="active",
                        rubric=updated.model_dump(mode="json"),
                        change_note=f"{row.id}: {row.title}" + (f" ({note})" if note else ""),
                        created_by="human-approved-proposal",
                        created_at=utcnow(),
                    )
                )
                row.resulting_version = updated.version
            row.status = (ProposalStatus.APPROVED if approve else ProposalStatus.REJECTED).value
            row.decided_at = utcnow()
            return proposal_model(row)

    # ----------------------------------------------------------------- stats
    async def stats(self, topic_id: str | None = None) -> StatsResponse:
        async with self.sessions() as s:
            runs = await self._finished_generate_runs(s, topic_id, None)
            first = await self._first_attempts(s, [r.id for r in runs])
            cost_stmt = select(RunRow.usage)
            if topic_id:
                cost_stmt = cost_stmt.where(RunRow.topic_id == topic_id)
            all_usage = (await s.scalars(cost_stmt)).all()
            guideline_counts = dict(
                (
                    await s.execute(
                        select(GuidelineRow.status, func.count()).group_by(GuidelineRow.status)
                    )
                ).all()
            )
            pending = await s.scalar(
                select(func.count())
                .select_from(RubricProposalRow)
                .where(RubricProposalRow.status == ProposalStatus.PENDING.value)
            )
        chronological = sorted(runs, key=lambda r: _utc(r.created_at))
        trend = []
        for r in chronological[-30:]:
            a1 = first.get(r.id)
            trend.append(
                RunTrendPoint(
                    run_id=r.id,
                    created_at=_utc(r.created_at),
                    status=r.status,
                    attempts=r.attempts_count or 0,
                    first_attempt_passed=bool(a1 and a1.passed),
                    first_attempt_failed_checks=len(a1.failed_check_ids or []) if a1 else 0,
                    guidelines_applied=len(r.guideline_ids_applied or []),
                    cost_usd=round(float((r.usage or {}).get("cost_usd", 0.0)), 4),
                )
            )
        total = len(runs)
        with_first = [r for r in runs if r.id in first]
        costs = [float((u or {}).get("cost_usd", 0.0)) for u in all_usage]
        return StatsResponse(
            runs_total=total,
            runs_shipped=sum(1 for r in runs if r.status == RunStatus.SHIPPED.value),
            runs_needs_review=sum(
                1 for r in runs if r.status == RunStatus.NEEDS_HUMAN_REVIEW.value
            ),
            first_pass_rate=(
                round(sum(1 for r in with_first if first[r.id].passed) / len(with_first), 3)
                if with_first
                else None
            ),
            avg_attempts=round(sum(r.attempts_count or 0 for r in runs) / total, 2)
            if total
            else None,
            avg_cost_usd=round(sum(costs) / len(costs), 4) if costs else None,
            total_cost_usd=round(sum(costs), 4),
            guidelines_active=guideline_counts.get(GuidelineStatus.ACTIVE.value, 0),
            guidelines_retired=guideline_counts.get(GuidelineStatus.RETIRED.value, 0),
            pending_proposals=pending or 0,
            trend=trend,
            checks=await self.failure_stats(topic_id),
        )
