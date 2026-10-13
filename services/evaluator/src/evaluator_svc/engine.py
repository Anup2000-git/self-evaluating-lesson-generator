"""The evaluation graph (LangGraph).

    START --Send--> deterministic (all 9 code checks)
          --Send--> judge x N      (one call per LLM-judged check, in parallel)
          --Send--> fact_check     (ReAct agent -> ACC-1, ACC-2)
          --Send--> learner        (simulated beginner -> COV-5)
    all branches --> report (join) --> END

Every check produces exactly one binary result. A check that crashes is reported as a
FAIL with ``details.error`` (fail-safe: an unevaluated lesson must never ship).
"""

from __future__ import annotations

import operator
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from evaluator_svc.checks.deterministic import run_deterministic
from evaluator_svc.checks.fact_checker import FactChecker
from evaluator_svc.checks.judges import Judge
from evaluator_svc.checks.learner import LearnerSimulator
from evaluator_svc.clients import KnowledgeClient, RubricProvider
from evaluator_svc.context import EvalContext
from evaluator_svc.settings import EvaluatorSettings
from lessongen_common.events import emit
from lessongen_common.llm import LLMProvider, usage_scope
from lessongen_common.logs import get_logger
from lessongen_common.schemas import (
    CheckMethod,
    CheckResult,
    CheckSpec,
    EvaluateRequest,
    EvaluationReport,
    EventType,
    Verdict,
)

log = get_logger(__name__)


class EvalState(TypedDict, total=False):
    plan: dict[str, list[str]]
    results: Annotated[list[CheckResult], operator.add]
    check_id: str


def error_result(spec: CheckSpec, exc: BaseException) -> CheckResult:
    return CheckResult(
        check_id=spec.id,
        dimension=spec.dimension,
        title=spec.title,
        method=spec.method,
        severity=spec.severity,
        verdict=Verdict.FAIL,
        reasoning=f"This check could not be evaluated ({type(exc).__name__}); it counts as FAIL so an "
        "unchecked lesson can never ship.",
        details={"error": str(exc)[:500]},
    )


def _ctx(config: RunnableConfig) -> EvalContext:
    return config["configurable"]["ctx"]


async def _publish(results: list[CheckResult]) -> None:
    for r in results:
        await emit(
            EventType.CHECK_COMPLETED,
            {
                "check_id": r.check_id,
                "title": r.title,
                "dimension": r.dimension.value,
                "method": r.method.value,
                "verdict": r.verdict.value,
                "reasoning": r.reasoning[:400],
                "votes": len(r.votes),
                "error": bool(r.details.get("error")),
            },
        )


class EvaluationEngine:
    def __init__(
        self,
        llm: LLMProvider,
        knowledge: KnowledgeClient,
        rubrics: RubricProvider,
        settings: EvaluatorSettings,
    ) -> None:
        self.knowledge = knowledge
        self.rubrics = rubrics
        self.judge = Judge(llm, settings)
        self.fact_checker = FactChecker(llm, knowledge, settings)
        self.learner = LearnerSimulator(llm, settings)
        self.graph = self._build()

    # ------------------------------------------------------------------ graph
    def _build(self) -> Any:
        graph = StateGraph(EvalState)
        graph.add_node("deterministic", self._deterministic)
        graph.add_node("judge", self._judge)
        graph.add_node("fact_check", self._fact_check)
        graph.add_node("learner", self._learner)
        graph.add_node("report", self._report)
        graph.add_conditional_edges(
            START, self._fan_out, ["deterministic", "judge", "fact_check", "learner", "report"]
        )
        for node in ("deterministic", "judge", "fact_check", "learner"):
            graph.add_edge(node, "report")
        graph.add_edge("report", END)
        return graph.compile(name="evaluation")

    @staticmethod
    def _fan_out(state: EvalState) -> list[Send]:
        plan = state["plan"]
        sends: list[Send] = []
        if plan.get(CheckMethod.DETERMINISTIC):
            sends.append(Send("deterministic", {}))
        sends += [Send("judge", {"check_id": cid}) for cid in plan.get(CheckMethod.LLM_JUDGE, [])]
        if plan.get(CheckMethod.FACT_CHECK):
            sends.append(Send("fact_check", {}))
        sends += [Send("learner", {"check_id": cid}) for cid in plan.get(CheckMethod.LEARNER, [])]
        return sends or [Send("report", {})]

    @staticmethod
    async def _guard(
        specs: list[CheckSpec], work: Callable[[], Awaitable[list[CheckResult]]]
    ) -> dict[str, list[CheckResult]]:
        started = time.perf_counter()
        try:
            results = await work()
        except Exception as exc:
            log.exception("check_failed_to_run", checks=[s.id for s in specs])
            results = [error_result(s, exc) for s in specs]
        elapsed = int((time.perf_counter() - started) * 1000)
        results = [
            r if r.latency_ms else r.model_copy(update={"latency_ms": elapsed}) for r in results
        ]
        await _publish(results)
        return {"results": results}

    async def _deterministic(self, state: EvalState, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        specs = ctx.rubric.of_method(CheckMethod.DETERMINISTIC)

        async def work() -> list[CheckResult]:
            out = []
            for spec in specs:
                try:
                    out.append(run_deterministic(ctx, spec))
                except Exception as exc:  # one broken check must not hide the others
                    log.exception("deterministic_check_crashed", check_id=spec.id)
                    out.append(error_result(spec, exc))
            return out

        return await self._guard(specs, work)

    async def _judge(self, state: EvalState, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        spec = ctx.rubric.by_id(state["check_id"])

        async def work() -> list[CheckResult]:
            return [await self.judge.judge(ctx, spec)]

        return await self._guard([spec], work)

    async def _fact_check(self, state: EvalState, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        specs = ctx.rubric.of_method(CheckMethod.FACT_CHECK)

        async def work() -> list[CheckResult]:
            return await self.fact_checker.run(ctx, specs)

        return await self._guard(specs, work)

    async def _learner(self, state: EvalState, config: RunnableConfig) -> dict[str, Any]:
        ctx = _ctx(config)
        spec = ctx.rubric.by_id(state["check_id"])

        async def work() -> list[CheckResult]:
            return [await self.learner.run(ctx, spec)]

        return await self._guard([spec], work)

    @staticmethod
    async def _report(state: EvalState) -> dict[str, Any]:
        return {}

    # -------------------------------------------------------------------- run
    async def evaluate(self, request: EvaluateRequest) -> EvaluationReport:
        started = time.perf_counter()
        with usage_scope() as usage:
            rubric = await self.rubrics.get(request.rubric_version)
            # The evaluator (only) may see the held-out learner questions.
            topic = await self.knowledge.topic(request.topic_id, include_assessment=True)
            ctx = EvalContext(
                lesson=request.lesson,
                topic=topic,
                rubric=rubric,
                helper_language=request.helper_language,
            )
            plan: dict[str, list[str]] = {}
            for check in rubric.checks:
                plan.setdefault(check.method.value, []).append(check.id)
            final = await self.graph.ainvoke(
                {"plan": plan, "results": []},
                config={"configurable": {"ctx": ctx}, "recursion_limit": 25},
            )
        report = EvaluationReport.build(
            rubric_version=rubric.version,
            results=final["results"],
            usage=usage,
            duration_ms=int((time.perf_counter() - started) * 1000),
            check_order=[c.id for c in rubric.checks],
        )
        await emit(
            EventType.EVALUATION_COMPLETED,
            {
                "passed": report.passed,
                "failed_check_ids": report.failed_check_ids,
                "summary": report.summary,
                "rubric_version": report.rubric_version,
                "cost_usd": report.usage.cost_usd,
                "duration_ms": report.duration_ms,
            },
        )
        log.info("evaluation_done", passed=report.passed, failed=report.failed_check_ids)
        return report
