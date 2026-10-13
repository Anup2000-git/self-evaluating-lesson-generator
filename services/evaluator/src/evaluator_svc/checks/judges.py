"""LLM-judged rubric checks: one focused binary question per call.

Design choices (each addresses a known LLM-as-judge failure mode):
* One check per call - avoids the "halo effect" where a judge that likes the lesson
  overall passes everything.
* Evidence first, verdict second, and quotes are verified against the lesson; a
  fabricated quote triggers one re-judgment.
* A FAIL is never accepted on one vote: a second, more careful vote confirms it and a
  third (stronger model) breaks ties. False FAILs cost a full regeneration, so they are
  worth an extra cheap call.
* Prompt layout [shared rules][lesson + topic reference][this check] keeps the long
  prefix identical across the ~11 judge calls so Azure prompt caching applies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from evaluator_svc.checks.evidence import unverified_quotes
from evaluator_svc.context import EvalContext
from evaluator_svc.settings import EvaluatorSettings
from lessongen_common.audience import AUDIENCE_SHORT
from lessongen_common.llm import LLMProvider, LLMRole, invoke_structured
from lessongen_common.prompts import PromptLibrary
from lessongen_common.schemas import CheckResult, CheckSpec, JudgeVote, Verdict

PROMPTS = PromptLibrary(Path(__file__).resolve().parent.parent / "prompts")


class JudgeVerdict(BaseModel):
    evidence: list[str] = Field(
        description="Up to 3 short quotes copied exactly from the lesson. Empty if something is missing."
    )
    reasoning: str = Field(description="2-4 sentences explaining the verdict.")
    verdict: Literal["PASS", "FAIL"]
    fix_instruction: str = Field(
        description="If FAIL: one specific instruction for the writer. If PASS: empty string."
    )


class Judge:
    def __init__(self, llm: LLMProvider, settings: EvaluatorSettings) -> None:
        self.llm = llm
        self.settings = settings

    def _prefix(self, ctx: EvalContext) -> list[BaseMessage]:
        cached = ctx.extras.get("judge_prefix")
        if cached is None:
            cached = [
                SystemMessage(
                    content=PROMPTS.render("judge_system.md.j2", audience=AUDIENCE_SHORT)
                ),
                HumanMessage(
                    content=PROMPTS.render(
                        "judge_context.md.j2",
                        lesson_markdown=ctx.lesson_markdown,
                        topic=ctx.topic,
                        helper_language=ctx.helper_language,
                    )
                ),
            ]
            ctx.extras["judge_prefix"] = cached
        return cached  # type: ignore[return-value]

    async def _vote(
        self, role: LLMRole, ctx: EvalContext, spec: CheckSpec, retry_note: str = ""
    ) -> JudgeVerdict:
        check_prompt = PROMPTS.render(
            "judge_check.md.j2",
            check_id=spec.id,
            title=spec.title,
            judge=ctx.rendered_judge(spec),
            retry_note=retry_note,
        )
        return await invoke_structured(
            self.llm,
            self.llm.get(role),
            JudgeVerdict,
            [*self._prefix(ctx), HumanMessage(content=check_prompt)],
            name=f"judge.{spec.id}",
        )

    async def _verified_vote(
        self, role: LLMRole, ctx: EvalContext, spec: CheckSpec
    ) -> tuple[JudgeVerdict, bool]:
        vote = await self._vote(role, ctx, spec)
        missing = unverified_quotes(
            vote.evidence, ctx.normalized_lesson, self.settings.evidence_match_threshold
        )
        if not missing:
            return vote, True
        note = (
            "Your previous answer quoted text that does not appear in the lesson: "
            + "; ".join(f'"{m[:120]}"' for m in missing)
            + ". Quote only text that is really in the lesson, copied exactly."
        )
        retry = await self._vote(role, ctx, spec, retry_note=note)
        still_missing = unverified_quotes(
            retry.evidence, ctx.normalized_lesson, self.settings.evidence_match_threshold
        )
        return retry, not still_missing

    async def judge(self, ctx: EvalContext, spec: CheckSpec) -> CheckResult:
        first, first_ok = await self._verified_vote(LLMRole.JUDGE, ctx, spec)
        votes: list[tuple[LLMRole, JudgeVerdict, bool]] = [(LLMRole.JUDGE, first, first_ok)]
        if first.verdict == "FAIL" and self.settings.judge_confirm_fails:
            second, second_ok = await self._verified_vote(LLMRole.JUDGE_CONFIRM, ctx, spec)
            votes.append((LLMRole.JUDGE_CONFIRM, second, second_ok))
            if second.verdict != first.verdict:
                third, third_ok = await self._verified_vote(LLMRole.JUDGE_TIEBREAK, ctx, spec)
                votes.append((LLMRole.JUDGE_TIEBREAK, third, third_ok))

        fails = sum(1 for _, v, _ in votes if v.verdict == "FAIL")
        final: Literal["PASS", "FAIL"] = "FAIL" if fails * 2 > len(votes) else "PASS"
        # Report the reasoning of the strongest vote that agrees with the final verdict.
        chosen_role, chosen, verified = next(
            (r, v, ok) for r, v, ok in reversed(votes) if v.verdict == final
        )
        fix = chosen.fix_instruction
        if final == "FAIL" and not fix.strip():
            fix = next((v.fix_instruction for _, v, _ in votes if v.fix_instruction.strip()), "")
        return CheckResult(
            check_id=spec.id,
            dimension=spec.dimension,
            title=spec.title,
            method=spec.method,
            severity=spec.severity,
            verdict=Verdict(final),
            reasoning=chosen.reasoning,
            evidence=chosen.evidence[:3],
            fix_instruction=fix if final == "FAIL" else "",
            evidence_verified=verified,
            votes=[
                JudgeVote(
                    model=self.llm.model_label(role),
                    verdict=Verdict(v.verdict),
                    reasoning=v.reasoning[:500],
                )
                for role, v, _ in votes
            ]
            if len(votes) > 1
            else [],
            details={"decided_by": self.llm.model_label(chosen_role), "votes": len(votes)},
        )
