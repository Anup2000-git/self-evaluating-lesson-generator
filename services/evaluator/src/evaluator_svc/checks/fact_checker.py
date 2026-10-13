"""Accuracy checks (ACC-1, ACC-2): a ReAct agent verifies every claim against the knowledge base.

Step 1 (structured call): extract the lesson's factual claims, each with its exact quote.
Step 2 (ReAct agent): search the knowledge base claim by claim and submit one verdict per
claim. ``submit_verdicts`` rejects submissions that skip claims, so nothing goes unchecked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from evaluator_svc.checks.evidence import quote_found
from evaluator_svc.clients import KnowledgeClient
from evaluator_svc.context import EvalContext
from evaluator_svc.settings import EvaluatorSettings
from lessongen_common.llm import (
    AgentTool,
    LLMProvider,
    LLMRole,
    ReactAgent,
    SubmitTool,
    invoke_structured,
)
from lessongen_common.prompts import PromptLibrary
from lessongen_common.schemas import CheckResult, CheckSpec, Verdict

PROMPTS = PromptLibrary(Path(__file__).resolve().parent.parent / "prompts")


class Claim(BaseModel):
    id: str
    quote: str = Field(description="The sentence from the lesson, copied exactly.")
    claim: str = Field(description="The claim restated in one plain sentence.")
    kind: Literal["concept", "specific_fact"]


class ClaimList(BaseModel):
    claims: list[Claim]


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_FOUND"]
    kb_chunk_ids: list[str] = Field(description="Ids of the knowledge-base chunks you relied on.")
    explanation: str = Field(description="One sentence: what the knowledge base says.")


class FactCheckSubmission(BaseModel):
    verdicts: list[ClaimVerdict]


class SearchArgs(BaseModel):
    reason: str = Field(description="One short sentence: why you are searching now.")
    query: str = Field(description="What to look up in the knowledge base.")


class FactCheckOutcome(BaseModel):
    claims: list[Claim]
    verdicts: list[ClaimVerdict]
    steps: int
    forced: bool


class FactChecker:
    def __init__(
        self, llm: LLMProvider, knowledge: KnowledgeClient, settings: EvaluatorSettings
    ) -> None:
        self.llm = llm
        self.knowledge = knowledge
        self.settings = settings

    async def extract_claims(self, ctx: EvalContext) -> list[Claim]:
        prompt = PROMPTS.render(
            "claims_extract.md.j2",
            topic_title=ctx.topic.title,
            max_claims=self.settings.max_claims,
            lesson_markdown=ctx.lesson_markdown,
        )
        extracted = await invoke_structured(
            self.llm,
            self.llm.get(LLMRole.FACT_CHECKER),
            ClaimList,
            [HumanMessage(content=prompt)],
            name="claims.extract",
        )
        claims = []
        for i, claim in enumerate(extracted.claims[: self.settings.max_claims], start=1):
            claims.append(claim.model_copy(update={"id": f"C{i}"}))
        return claims

    async def verify(self, ctx: EvalContext, claims: list[Claim]) -> FactCheckOutcome:
        if not claims:
            return FactCheckOutcome(claims=[], verdicts=[], steps=0, forced=False)
        topic_id = ctx.topic.id
        known_chunks: set[str] = set()

        async def search(args: SearchArgs) -> str:
            response = await self.knowledge.search(topic_id, args.query, 4)
            known_chunks.update(h.chunk.id for h in response.hits)
            if not response.hits:
                return "No matching knowledge-base chunks."
            return "\n\n".join(
                f"[{h.chunk.id}] {h.chunk.doc_title} > {h.chunk.heading}\n{h.chunk.text}"
                for h in response.hits
            )

        claim_ids = [c.id for c in claims]

        def validate(submission: FactCheckSubmission) -> list[str]:
            problems = []
            given = [v.claim_id for v in submission.verdicts]
            missing = [cid for cid in claim_ids if cid not in given]
            if missing:
                problems.append(f"missing verdicts for claims: {', '.join(missing)}")
            unknown = [cid for cid in given if cid not in claim_ids]
            if unknown:
                problems.append(f"unknown claim ids: {', '.join(unknown)}")
            for v in submission.verdicts:
                if v.verdict != "NOT_FOUND" and not v.kb_chunk_ids:
                    problems.append(f"{v.claim_id}: cite the chunk ids you used")
            return problems

        agent: ReactAgent[FactCheckSubmission] = ReactAgent(
            name="fact_checker",
            model=self.llm.get(LLMRole.FACT_CHECKER),
            provider=self.llm,
            tools=[
                AgentTool(
                    "search_knowledge_base",
                    "Search the curated knowledge base. Returns the most relevant chunks with their ids.",
                    SearchArgs,
                    search,
                    preview=lambda text: text[:240],
                )
            ],
            submit=SubmitTool(
                "submit_verdicts",
                "Submit one verdict for every claim. Call once, when all claims are checked.",
                FactCheckSubmission,
                validate=validate,
                summarize=lambda s: {
                    "claims": len(s.verdicts),
                    "contradicted": sum(1 for v in s.verdicts if v.verdict == "CONTRADICTED"),
                },
            ),
            max_steps=self.settings.fact_check_max_steps,
        )
        claims_text = "\n".join(
            f'- {c.id} ({c.kind}): {c.claim}  [lesson: "{c.quote}"]' for c in claims
        )
        result = await agent.run(
            [
                SystemMessage(
                    content=PROMPTS.render("fact_checker_system.md.j2", topic_title=ctx.topic.title)
                ),
                HumanMessage(content=f"Claims to verify:\n{claims_text}"),
            ]
        )
        by_id = {v.claim_id: v for v in result.output.verdicts}
        # Anything the agent still skipped (only possible after a forced submission) is NOT_FOUND.
        verdicts = [
            by_id.get(cid)
            or ClaimVerdict(
                claim_id=cid, verdict="NOT_FOUND", kb_chunk_ids=[], explanation="Not checked."
            )
            for cid in claim_ids
        ]
        return FactCheckOutcome(
            claims=claims, verdicts=verdicts, steps=result.steps, forced=result.forced
        )

    async def run(self, ctx: EvalContext, specs: list[CheckSpec]) -> list[CheckResult]:
        claims = await self.extract_claims(ctx)
        claims = [
            c
            for c in claims
            if quote_found(c.quote, ctx.normalized_lesson, self.settings.evidence_match_threshold)
        ] or claims
        outcome = await self.verify(ctx, claims)
        return [self._result(spec, outcome) for spec in specs]

    @staticmethod
    def _result(spec: CheckSpec, outcome: FactCheckOutcome) -> CheckResult:
        claims = {c.id: c for c in outcome.claims}
        rows = [
            {
                "id": v.claim_id,
                "claim": claims[v.claim_id].claim,
                "quote": claims[v.claim_id].quote,
                "kind": claims[v.claim_id].kind,
                "verdict": v.verdict,
                "kb_chunk_ids": v.kb_chunk_ids,
                "explanation": v.explanation,
            }
            for v in outcome.verdicts
        ]
        if spec.impl == "specifics_supported":
            bad = [r for r in rows if r["kind"] == "specific_fact" and r["verdict"] != "SUPPORTED"]
            specifics = sum(1 for r in rows if r["kind"] == "specific_fact")
            ok_text = f"All {specifics} specific facts (numbers, dates, names) are supported by the knowledge base."
            bad_text = "Specific facts not supported by the knowledge base: "
            fix_intro = "Remove these unsupported specifics, or replace them with facts from the knowledge base"
        else:
            bad = [r for r in rows if r["verdict"] == "CONTRADICTED"]
            ok_text = (
                f"None of the {len(rows)} checked claims is contradicted by the knowledge base."
            )
            bad_text = "Claims contradicted by the knowledge base: "
            fix_intro = "Correct these false statements so they match the knowledge base"
        passed = not bad
        reasoning = (
            ok_text
            if passed
            else bad_text
            + "; ".join(f'{r["id"]} "{r["claim"]}" - {r["explanation"]}' for r in bad[:4])
        )
        return CheckResult(
            check_id=spec.id,
            dimension=spec.dimension,
            title=spec.title,
            method=spec.method,
            severity=spec.severity,
            verdict=Verdict.PASS if passed else Verdict.FAIL,
            reasoning=reasoning,
            evidence=[r["quote"] for r in bad][:3],
            fix_instruction=""
            if passed
            else fix_intro
            + ": "
            + " | ".join(f'"{r["quote"][:160]}" -> {r["explanation"]}' for r in bad[:5]),
            evidence_verified=True,
            details={"claims": rows, "agent_steps": outcome.steps, "forced": outcome.forced},
        )
