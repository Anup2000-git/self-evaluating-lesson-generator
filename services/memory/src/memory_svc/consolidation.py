"""Memory consolidation - the self-evolving step that runs after every lesson run.

    1. Effectiveness (deterministic): every guideline injected into this run gets
       "helped" if its linked checks passed on attempt 1, otherwise "missed".
    2. Reflection (LLM): failures, what fixed them and human comments become new
       guidelines; guidelines whose check failed again are sharpened.
    3. Guardrails (deterministic): ineffective guidelines are retired, the active set per
       topic is capped, near-duplicates are rejected.
    4. Escalation: a check that keeps failing on the first attempt despite guidelines is
       raised to a human as a proposal.
    5. Human overrides ("the evaluator was wrong on X") become rubric clarification
       proposals - applied only after a human approves them.

The writer's prompts evolve automatically; the rubric (the quality bar) never does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from lessongen_common.audience import AUDIENCE_SHORT
from lessongen_common.events import emit
from lessongen_common.llm import (
    LLMNotConfiguredError,
    LLMProvider,
    LLMRole,
    invoke_structured,
    usage_scope,
)
from lessongen_common.logs import get_logger
from lessongen_common.prompts import PromptLibrary
from lessongen_common.schemas import (
    CheckMethod,
    ConsolidationResult,
    EffectivenessUpdate,
    EventType,
    Feedback,
    Guideline,
    GuidelineOrigin,
    GuidelineStatus,
    GuidelineTarget,
    GuidelineUpdate,
    ProposalKind,
    ProposalStatus,
    RunDetail,
    RunMode,
)
from memory_svc.repository import MemoryRepository
from memory_svc.settings import MemorySettings

log = get_logger(__name__)
PROMPTS = PromptLibrary(Path(__file__).parent / "prompts")


# ---------------------------------------------------------------- LLM schemas
class NewGuideline(BaseModel):
    text: str = Field(description="One imperative instruction for the writer, at most 35 words.")
    check_ids: list[str] = Field(description="Rubric check ids this guideline prevents.")
    target: Literal["planner", "writer", "both"]
    source: Literal["failure", "feedback"]
    rationale: str


class SharpenGuideline(BaseModel):
    guideline_id: str
    new_text: str = Field(description="The improved, more concrete guideline (max 35 words).")
    rationale: str


class RetireGuideline(BaseModel):
    guideline_id: str
    rationale: str


class ReflectionOutput(BaseModel):
    new_guidelines: list[NewGuideline]
    sharpen: list[SharpenGuideline]
    retire: list[RetireGuideline]


class Clarification(BaseModel):
    title: str = Field(description="Short title of the proposed rubric change.")
    add_notes: list[str]
    add_pass_criteria: list[str]
    add_fail_criteria: list[str]
    rationale: str


# --------------------------------------------------------------- helpers
def failure_episodes(run: RunDetail) -> list[dict[str, str | int]]:
    """Every failed check, why it failed, and (if it was) what fixed it later."""
    attempts = sorted(run.attempts, key=lambda a: a.attempt_no)
    episodes: list[dict[str, str | int]] = []
    for index, attempt in enumerate(attempts):
        later = attempts[index + 1] if index + 1 < len(attempts) else None
        for result in attempt.evaluation.failed_results():
            fixed_by = ""
            if later and result.check_id not in later.evaluation.failed_check_ids:
                notes = [n.change for n in later.revision_notes if n.check_id == result.check_id]
                fixed_by = notes[0] if notes else "a revision (no note given)"
            episodes.append(
                {
                    "attempt": attempt.attempt_no,
                    "check_id": result.check_id,
                    "title": result.title,
                    "reasoning": result.reasoning[:600],
                    "evidence": (result.evidence[0][:300] if result.evidence else ""),
                    "fixed_by": fixed_by[:400],
                }
            )
    return episodes


def effectiveness_updates(
    run: RunDetail, guidelines: dict[str, Guideline]
) -> list[EffectivenessUpdate]:
    first = next((a for a in run.attempts if a.attempt_no == 1), None)
    if first is None:
        return []
    failed = set(first.evaluation.failed_check_ids)
    updates = []
    for gid in run.guideline_ids_applied:
        guideline = guidelines.get(gid)
        if guideline is None or not guideline.check_ids:
            continue
        outcome = "missed" if failed & set(guideline.check_ids) else "helped"
        updates.append(
            EffectivenessUpdate(guideline_id=gid, check_ids=guideline.check_ids, outcome=outcome)
        )
    return updates


def _is_duplicate(text: str, existing: list[Guideline]) -> Guideline | None:
    for g in existing:
        if fuzz.token_set_ratio(text.lower(), g.text.lower()) >= 88:
            return g
    return None


class Consolidator:
    def __init__(self, repo: MemoryRepository, llm: LLMProvider, settings: MemorySettings) -> None:
        self.repo = repo
        self.llm = llm
        self.settings = settings

    async def consolidate(self, run_id: str | None) -> ConsolidationResult:
        result = ConsolidationResult(run_id=run_id)
        notes: list[str] = []
        with usage_scope() as usage:
            run = await self.repo.get_run(run_id) if run_id else None
            topic_id = run.topic_id if run else None
            if run is not None and run.mode == RunMode.EVALUATE_ONLY:
                notes.append("evaluate-only run: nothing to learn about writing")
                run = None

            if run is not None:
                all_guidelines = {g.id: g for g in await self.repo.list_guidelines()}
                result.effectiveness = effectiveness_updates(run, all_guidelines)
                await self.repo.record_effectiveness(result.effectiveness)

            feedback = await self.repo.list_feedback(processed=False)
            if run is not None or feedback:
                await self._reflect(run, topic_id, feedback, result, notes)
            await self._proposals_from_overrides(feedback, result, notes)
            await self.repo.mark_feedback_processed([f.id for f in feedback])
            result.feedback_processed = len(feedback)

            if topic_id:
                await self._apply_guardrails(topic_id, result)
                await self._escalate(topic_id, result)
            if run is not None:
                await self.repo.mark_consolidated(run.id)
        result.usage = usage
        result.summary = self._summary(result, notes)
        await emit(
            EventType.MEMORY_CONSOLIDATED,
            {
                "summary": result.summary,
                "added": [g.id for g in result.added],
                "sharpened": [g.id for g in result.sharpened],
                "retired": [g.id for g in result.retired],
                "proposals": [p.id for p in result.proposals],
            },
        )
        log.info("memory_consolidated", run_id=run_id, summary=result.summary)
        return result

    # ------------------------------------------------------------ reflection
    async def _reflect(
        self,
        run: RunDetail | None,
        topic_id: str | None,
        feedback: list[Feedback],
        result: ConsolidationResult,
        notes: list[str],
    ) -> None:
        episodes = failure_episodes(run) if run else []
        comments = [f for f in feedback if f.comment.strip()]
        if not episodes and not comments:
            notes.append("first attempt passed - no new lessons to learn")
            return
        active = [
            g
            for g in await self.repo.list_guidelines(status=GuidelineStatus.ACTIVE.value)
            if g.topic_id in (None, topic_id)
        ]
        messages = [
            SystemMessage(
                content=PROMPTS.render("reflector_system.md.j2", audience=AUDIENCE_SHORT)
            ),
            HumanMessage(
                content=PROMPTS.render(
                    "reflector_user.md.j2",
                    topic_id=topic_id or "unknown",
                    guidelines=active,
                    episodes=episodes,
                    comments=[{"rating": c.rating, "comment": c.comment[:800]} for c in comments],
                )
            ),
        ]
        try:
            output = await invoke_structured(
                self.llm,
                self.llm.get(LLMRole.REFLECTOR),
                ReflectionOutput,
                messages,
                name="reflector",
            )
        except LLMNotConfiguredError:
            notes.append("reflection skipped: Azure OpenAI is not configured")
            return

        valid_checks = {str(e["check_id"]) for e in episodes}
        by_id = {g.id: g for g in active}
        run_id = run.id if run else None
        for item in output.new_guidelines[:3]:
            text = " ".join(item.text.split())[:400]
            check_ids = [c for c in item.check_ids if c in valid_checks] or (
                item.check_ids[:3] if item.source == "feedback" else []
            )
            if not text or (item.source == "failure" and not check_ids):
                continue
            duplicate = _is_duplicate(text, active)
            if duplicate is not None:
                sharpened = await self.repo.update_guideline(
                    duplicate.id,
                    GuidelineUpdate(
                        text=text,
                        reason=f"merged near-duplicate from run {run_id}: {item.rationale[:200]}",
                    ),
                )
                result.sharpened.append(sharpened)
                continue
            added = await self.repo.add_guideline(
                topic_id=topic_id,
                text=text,
                check_ids=check_ids,
                target=GuidelineTarget(item.target),
                origin=GuidelineOrigin.FEEDBACK
                if item.source == "feedback"
                else GuidelineOrigin.FAILURE,
                created_from_run=run_id,
                reason=item.rationale[:300],
            )
            result.added.append(added)
            active.append(added)
        for item in output.sharpen:
            if item.guideline_id in by_id and item.new_text.strip():
                result.sharpened.append(
                    await self.repo.update_guideline(
                        item.guideline_id,
                        GuidelineUpdate(
                            text=item.new_text[:400],
                            reason=f"sharpened after run {run_id}: {item.rationale[:200]}",
                        ),
                    )
                )
        for item in output.retire:
            if item.guideline_id in by_id:
                result.retired.append(
                    await self.repo.update_guideline(
                        item.guideline_id,
                        GuidelineUpdate(
                            status=GuidelineStatus.RETIRED, reason=item.rationale[:300]
                        ),
                    )
                )

    # ------------------------------------------------------------- guardrails
    async def _apply_guardrails(self, topic_id: str, result: ConsolidationResult) -> None:
        active = [
            g
            for g in await self.repo.list_guidelines(status=GuidelineStatus.ACTIVE.value)
            if g.topic_id in (None, topic_id)
        ]
        for g in active:
            if g.times_missed >= self.settings.retire_after_misses and g.times_helped == 0:
                result.retired.append(
                    await self.repo.update_guideline(
                        g.id,
                        GuidelineUpdate(
                            status=GuidelineStatus.RETIRED,
                            reason=f"ineffective: its checks still failed {g.times_missed} times",
                        ),
                    )
                )
        retired_ids = {g.id for g in result.retired}
        remaining = [g for g in active if g.id not in retired_ids]
        overflow = len(remaining) - self.settings.max_active_guidelines_per_topic
        if overflow > 0:
            weakest = sorted(
                remaining,
                key=lambda g: (
                    (g.times_helped + 1) / (g.times_helped + g.times_missed + 2),
                    g.updated_at,
                ),
            )[:overflow]
            for g in weakest:
                result.retired.append(
                    await self.repo.update_guideline(
                        g.id,
                        GuidelineUpdate(
                            status=GuidelineStatus.RETIRED, reason="capacity: lowest effectiveness"
                        ),
                    )
                )

    async def _escalate(self, topic_id: str, result: ConsolidationResult) -> None:
        stats = await self.repo.failure_stats(topic_id, self.settings.escalation_window_runs)
        pending = {
            p.check_id
            for p in await self.repo.list_proposals(ProposalStatus.PENDING.value)
            if p.source == "escalation"
        }
        for stat in stats:
            if (
                stat.first_attempt_failures < self.settings.escalation_min_failures
                or stat.check_id in pending
            ):
                continue
            result.proposals.append(
                await self.repo.create_proposal(
                    check_id=stat.check_id,
                    kind=ProposalKind.PROMPT_CHANGE,
                    title=(
                        f"Persistent failure: {stat.check_id} failed on the first attempt in "
                        f"{stat.first_attempt_failures} of the last {stat.runs} runs"
                    ),
                    proposed_change={
                        "check_id": stat.check_id,
                        "suggestion": "Learned guidelines are not enough. Review the writer's "
                        "prompt/template for this check, or whether the check itself is too vague.",
                    },
                    rationale="Self-evolving guidelines did not fix this failure pattern, so a human should look at it.",
                    evidence=[f"first-attempt fail rate {stat.first_attempt_fail_rate:.0%}"],
                    source="escalation",
                )
            )

    # -------------------------------------------------------------- overrides
    async def _proposals_from_overrides(
        self, feedback: list[Feedback], result: ConsolidationResult, notes: list[str]
    ) -> None:
        overrides = [(f, o) for f in feedback for o in f.check_overrides]
        if not overrides:
            return
        rubric = (await self.repo.active_rubric()).rubric
        for fb, override in overrides:
            try:
                check = rubric.by_id(override.check_id)
            except KeyError:
                continue
            run = await self.repo.get_run(fb.run_id)
            final = run.final_attempt() or (run.attempts[-1] if run.attempts else None)
            automated = (
                next((r for r in final.evaluation.results if r.check_id == check.id), None)
                if final
                else None
            )
            if automated is not None and automated.verdict == override.human_verdict:
                continue  # human agrees with the evaluator - nothing to clarify
            if check.method != CheckMethod.LLM_JUDGE:
                result.proposals.append(
                    await self.repo.create_proposal(
                        check_id=check.id,
                        kind=ProposalKind.PROMPT_CHANGE,
                        title=f"Review {check.id} ({check.method.value}) - a reviewer disagreed",
                        proposed_change={
                            "check_id": check.id,
                            "human_verdict": override.human_verdict.value,
                        },
                        rationale=override.note
                        or "Reviewer marked the automated verdict as wrong.",
                        evidence=[automated.reasoning[:300]] if automated else [],
                        source="feedback",
                    )
                )
                continue
            prompt = PROMPTS.render(
                "clarify_check.md.j2",
                check=check,
                automated_verdict=automated.verdict.value if automated else "unknown",
                automated_reasoning=(automated.reasoning[:600] if automated else "n/a"),
                human_verdict=override.human_verdict.value,
                human_note=override.note[:800],
            )
            try:
                clarification = await invoke_structured(
                    self.llm,
                    self.llm.get(LLMRole.REFLECTOR),
                    Clarification,
                    [HumanMessage(content=prompt)],
                    name="clarify_check",
                )
            except LLMNotConfiguredError:
                notes.append("clarification skipped: Azure OpenAI is not configured")
                return
            result.proposals.append(
                await self.repo.create_proposal(
                    check_id=check.id,
                    kind=ProposalKind.CLARIFY_CHECK,
                    title=clarification.title[:200],
                    proposed_change={
                        "check_id": check.id,
                        "add_notes": clarification.add_notes[:3],
                        "add_pass_criteria": clarification.add_pass_criteria[:2],
                        "add_fail_criteria": clarification.add_fail_criteria[:2],
                    },
                    rationale=clarification.rationale[:600],
                    evidence=[
                        f"evaluator said {automated.verdict.value if automated else '?'}; "
                        f"reviewer said {override.human_verdict.value}: {override.note[:200]}"
                    ],
                    source="feedback",
                )
            )

    @staticmethod
    def _summary(result: ConsolidationResult, notes: list[str]) -> str:
        helped = sum(1 for e in result.effectiveness if e.outcome == "helped")
        parts = [
            f"{len(result.added)} new guideline(s)",
            f"{len(result.sharpened)} sharpened",
            f"{len(result.retired)} retired",
            f"{len(result.proposals)} proposal(s) for human review",
        ]
        if result.effectiveness:
            parts.append(f"{helped}/{len(result.effectiveness)} applied guidelines helped")
        if result.feedback_processed:
            parts.append(f"{result.feedback_processed} feedback item(s) processed")
        text = ", ".join(parts)
        return text + (f" ({'; '.join(notes)})" if notes else "")


__all__ = ["Consolidator", "ReflectionOutput", "effectiveness_updates", "failure_episodes"]
