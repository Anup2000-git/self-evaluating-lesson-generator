r"""The agentic loop as a LangGraph state machine.

    START -> recall_memory -> plan -> write -> evaluate --route--> finalize -> consolidate_memory -> END
                         \                       ^   |  \--> revise --(new attempt)--> evaluate
                          \--(repair: lesson given)  |  \--> evaluate (only evaluation errors)
    START (evaluate_only) ----------------------------+   \--> select_best -> finalize

Control flow is deterministic (a graph, not a free-form agent): the loop always
terminates because ``route_after_evaluate`` caps retries and cost, and LangGraph's
recursion limit is a final backstop. Agents (planner, writer, fact-checker) run inside
the nodes, in other services. Every node is checkpointed, so a crashed worker resumes
from the last completed node.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.graph import END, START, StateGraph

from lessongen_common.clients import EvaluatorClient, GeneratorClient, MemoryClient
from lessongen_common.context import bind_context
from lessongen_common.events import emit
from lessongen_common.logs import get_logger
from lessongen_common.schemas import (
    AttemptKind,
    AttemptRecord,
    EvaluateRequest,
    EvaluationReport,
    EventType,
    GenerationContext,
    Lesson,
    LessonPlan,
    MemoryContext,
    PlanRequest,
    ReviseRequest,
    RevisionNote,
    RunMode,
    RunStatus,
    RunUpdate,
    Usage,
    WriteRequest,
)
from orchestrator_svc.graph.policy import (
    choose_strategy,
    route_after_evaluate,
    section_diff,
    select_best,
)
from orchestrator_svc.graph.state import PipelineState, merge_usage
from orchestrator_svc.jobs import Job
from orchestrator_svc.settings import OrchestratorSettings

log = get_logger(__name__)

NodeFn = Callable[[PipelineState], Awaitable[dict[str, Any]]]


class RunCancelled(Exception):
    """Raised between nodes when a user cancelled the run."""


def initial_state(job: Job) -> PipelineState:
    state: PipelineState = {
        "run_id": job.run_id,
        "mode": job.mode.value,
        "topic": job.topic,
        "topic_id": job.topic_id,
        "topic_title": job.topic_title,
        "helper_language": job.helper_language,
        "max_retries": job.max_retries,
        "fault_id": job.fault_id,
        "memory": {"topic_id": job.topic_id},
        "plan": None,
        "previous_lesson": None,
        "evaluation": None,
        "pending_notes": [],
        "pending_strategy_reason": "",
        "pending_generation_usage": {},
        "eval_retries": 0,
        "attempts": [],
        "usage": {},
        "status": RunStatus.RUNNING.value,
        "status_reason": None,
        "final_attempt_no": None,
        "consolidation": None,
    }
    if job.initial_lesson is not None:
        state.update(
            lesson=job.initial_lesson.model_dump(mode="json"),
            attempt=1,
            pending_kind=AttemptKind.PROVIDED.value,
        )
    else:
        state.update(lesson=None, attempt=0, pending_kind=AttemptKind.INITIAL.value)
    return state


class Pipeline:
    def __init__(
        self,
        *,
        memory: MemoryClient,
        generator: GeneratorClient,
        evaluator: EvaluatorClient,
        settings: OrchestratorSettings,
        is_cancelled: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.memory = memory
        self.generator = generator
        self.evaluator = evaluator
        self.settings = settings
        self.is_cancelled = is_cancelled

    # ------------------------------------------------------------- wiring
    def build(self, checkpointer: Any = None) -> Any:
        graph = StateGraph(PipelineState)
        graph.add_node("recall_memory", self._node("recall_memory", self._recall_memory))
        graph.add_node("plan", self._node("plan", self._plan))
        graph.add_node("write", self._node("write", self._write))
        graph.add_node("evaluate", self._node("evaluate", self._evaluate))
        graph.add_node("revise", self._node("revise", self._revise))
        graph.add_node("select_best", self._node("select_best", self._select_best))
        graph.add_node("finalize", self._node("finalize", self._finalize))
        graph.add_node("consolidate_memory", self._node("consolidate_memory", self._consolidate))

        graph.add_conditional_edges(START, self._entry, ["recall_memory", "evaluate"])
        graph.add_conditional_edges("recall_memory", self._after_recall, ["plan", "evaluate"])
        graph.add_edge("plan", "write")
        graph.add_edge("write", "evaluate")
        graph.add_conditional_edges(
            "evaluate", lambda s: s["route"], ["finalize", "evaluate", "revise", "select_best"]
        )
        graph.add_edge("revise", "evaluate")
        graph.add_edge("select_best", "finalize")
        graph.add_conditional_edges("finalize", self._after_finalize, ["consolidate_memory", END])
        graph.add_edge("consolidate_memory", END)
        return graph.compile(checkpointer=checkpointer, name="lesson_pipeline")

    @staticmethod
    def _entry(state: PipelineState) -> str:
        return "evaluate" if state["mode"] == RunMode.EVALUATE_ONLY.value else "recall_memory"

    @staticmethod
    def _after_recall(state: PipelineState) -> str:
        return "evaluate" if state.get("lesson") else "plan"

    @staticmethod
    def _after_finalize(state: PipelineState) -> str:
        return END if state["mode"] == RunMode.EVALUATE_ONLY.value else "consolidate_memory"

    def _node(self, name: str, fn: NodeFn) -> NodeFn:
        async def run(state: PipelineState) -> dict[str, Any]:
            run_id = state["run_id"]
            if self.is_cancelled is not None and await self.is_cancelled(run_id):
                raise RunCancelled(run_id)
            attempt = state.get("attempt") or 0
            if name == "write":
                attempt = 1
            elif name == "revise":
                attempt += 1
            with bind_context(run_id=run_id, attempt=attempt or None, node=name):
                started = time.perf_counter()
                await emit(EventType.NODE_STARTED, {"node": name})
                update = await fn(state)
                summary = update.pop("_summary", "")
                node_usage = Usage.model_validate(update.get("usage") or {})
                await emit(
                    EventType.NODE_COMPLETED,
                    {
                        "node": name,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "summary": summary,
                        "cost_usd": round(node_usage.cost_usd, 4),
                        "llm_calls": node_usage.llm_calls,
                    },
                )
                return update

        run.__name__ = name
        return run

    @staticmethod
    def _context(state: PipelineState) -> GenerationContext:
        return GenerationContext(
            topic_id=state["topic_id"],
            topic_title=state["topic_title"],
            helper_language=state["helper_language"],
            memory=MemoryContext.model_validate(
                state.get("memory") or {"topic_id": state["topic_id"]}
            ),
        )

    # -------------------------------------------------------------- nodes
    async def _recall_memory(self, state: PipelineState) -> dict[str, Any]:
        context = await self.memory.context(state["topic_id"])
        ids = [g.id for g in context.guidelines]
        await self.memory.update_run(state["run_id"], RunUpdate(guideline_ids_applied=ids))
        await emit(
            EventType.MEMORY_RECALLED,
            {
                "guidelines": [
                    {"id": g.id, "text": g.text, "check_ids": g.check_ids, "target": g.target.value}
                    for g in context.guidelines
                ],
                "frequent_failures": [f.model_dump() for f in context.frequent_failures],
                "human_notes": len(context.human_notes),
            },
        )
        return {
            "memory": context.model_dump(mode="json"),
            "_summary": f"{len(ids)} learned guideline(s), {len(context.frequent_failures)} frequent failure(s)",
        }

    async def _plan(self, state: PipelineState) -> dict[str, Any]:
        response = await self.generator.plan(PlanRequest(context=self._context(state)))
        await self.memory.update_run(state["run_id"], RunUpdate(plan=response.plan))
        return {
            "plan": response.plan.model_dump(mode="json"),
            "usage": response.usage.model_dump(mode="json"),
            "_summary": f"{len(response.plan.sections)} sections planned",
        }

    async def _write(self, state: PipelineState) -> dict[str, Any]:
        response = await self.generator.write(
            WriteRequest(
                context=self._context(state), plan=LessonPlan.model_validate(state["plan"])
            )
        )
        usage = response.usage.model_dump(mode="json")
        return {
            "lesson": response.lesson.model_dump(mode="json"),
            "previous_lesson": None,
            "attempt": 1,
            "pending_kind": AttemptKind.INITIAL.value,
            "pending_notes": [],
            "pending_strategy_reason": "",
            "pending_generation_usage": usage,
            "eval_retries": 0,
            "usage": usage,
            "_summary": f"first draft written in {response.agent_steps} agent step(s)",
        }

    async def _evaluate(self, state: PipelineState) -> dict[str, Any]:
        lesson = Lesson.model_validate(state["lesson"])
        report = await self.evaluator.evaluate(
            EvaluateRequest(
                lesson=lesson, topic_id=state["topic_id"], helper_language=state["helper_language"]
            )
        )
        previous = (
            Lesson.model_validate(state["previous_lesson"])
            if state.get("previous_lesson")
            else None
        )
        record = AttemptRecord(
            attempt_no=state["attempt"],
            kind=AttemptKind(state["pending_kind"]),
            lesson=lesson,
            evaluation=report,
            revision_notes=[
                RevisionNote.model_validate(n) for n in state.get("pending_notes") or []
            ],
            diff=section_diff(previous, lesson),
            strategy_reason=state.get("pending_strategy_reason") or "",
            generation_usage=Usage.model_validate(state.get("pending_generation_usage") or {}),
            created_at=datetime.now(UTC),
        )
        await self.memory.save_attempt(state["run_id"], record)

        cost_so_far = Usage.model_validate(
            merge_usage(state.get("usage"), report.usage.model_dump())
        ).cost_usd
        route, reason = route_after_evaluate(
            mode=RunMode(state["mode"]),
            report=report,
            attempt=state["attempt"],
            max_retries=state["max_retries"],
            cost_usd=cost_so_far,
            budget_usd=self.settings.run_budget_usd,
            eval_retries_used=state.get("eval_retries", 0),
            eval_retries_allowed=self.settings.evaluation_error_retries,
        )
        if not report.passed:
            await emit(
                EventType.ATTEMPT_REJECTED,
                {
                    "attempt": state["attempt"],
                    "failed_check_ids": report.failed_check_ids,
                    "summary": report.summary,
                    "next": route,
                    "reason": reason,
                },
            )
        update: dict[str, Any] = {
            "evaluation": report.model_dump(mode="json"),
            "attempts": [record.model_dump(mode="json")],
            "usage": report.usage.model_dump(mode="json"),
            "route": route,
            "route_reason": reason,
            "_summary": f"{report.summary} -> {route} ({reason})",
        }
        if route == "evaluate":
            update["eval_retries"] = state.get("eval_retries", 0) + 1
        return update

    async def _revise(self, state: PipelineState) -> dict[str, Any]:
        report = EvaluationReport.model_validate(state["evaluation"])
        strategy, reason = choose_strategy(report, self.settings.patch_max_failed_checks)
        response = await self.generator.revise(
            ReviseRequest(
                context=self._context(state),
                plan=LessonPlan.model_validate(state["plan"]) if state.get("plan") else None,
                previous_lesson=Lesson.model_validate(state["lesson"]),
                failed=report.failed_results(),
                passed_check_ids=[r.check_id for r in report.results if r.passed],
                strategy=strategy,
            )
        )
        new_attempt = state["attempt"] + 1
        await emit(
            EventType.REVISION_COMPLETED,
            {
                "attempt": new_attempt,
                "strategy": strategy.value,
                "reason": reason,
                "notes": [n.model_dump() for n in response.revision_notes],
            },
        )
        usage = response.usage.model_dump(mode="json")
        return {
            "previous_lesson": state["lesson"],
            "lesson": response.lesson.model_dump(mode="json"),
            "attempt": new_attempt,
            "pending_kind": strategy.value,
            "pending_notes": [n.model_dump(mode="json") for n in response.revision_notes],
            "pending_strategy_reason": reason,
            "pending_generation_usage": usage,
            "eval_retries": 0,
            "usage": usage,
            "_summary": f"attempt {new_attempt}: {strategy.value} with {len(response.revision_notes)} fix note(s)",
        }

    async def _select_best(self, state: PipelineState) -> dict[str, Any]:
        attempts = [AttemptRecord.model_validate(a) for a in state["attempts"]]
        best = select_best(attempts)
        failing = ", ".join(best.evaluation.failed_check_ids)
        reason = f"{state.get('route_reason', 'stopped')}; best attempt is #{best.attempt_no}, still failing: {failing}"
        return {
            "final_attempt_no": best.attempt_no,
            "status": RunStatus.NEEDS_HUMAN_REVIEW.value,
            "status_reason": reason,
            "_summary": f"escalated to a human: {reason}",
        }

    async def _finalize(self, state: PipelineState) -> dict[str, Any]:
        mode = RunMode(state["mode"])
        status = RunStatus(state.get("status") or RunStatus.RUNNING.value)
        final_no = state.get("final_attempt_no")
        reason = state.get("status_reason")
        if status == RunStatus.RUNNING:
            report = EvaluationReport.model_validate(state["evaluation"])
            final_no = state["attempt"]
            if mode == RunMode.EVALUATE_ONLY:
                status, reason = RunStatus.EVALUATED, report.summary
            elif report.passed:
                status = RunStatus.SHIPPED
                reason = f"passed all {len(report.results)} checks on attempt {final_no}"
            else:  # defensive: the router never sends a failing lesson here in generate/repair mode
                status, reason = RunStatus.NEEDS_HUMAN_REVIEW, report.summary
        await self.memory.update_run(
            state["run_id"],
            RunUpdate(
                status=status,
                status_reason=reason,
                final_attempt_no=final_no,
                usage=Usage.model_validate(state.get("usage") or {}),
                finished_at=datetime.now(UTC),
            ),
        )
        return {
            "status": status.value,
            "status_reason": reason,
            "final_attempt_no": final_no,
            "_summary": f"{status.value}: {reason}",
        }

    async def _consolidate(self, state: PipelineState) -> dict[str, Any]:
        try:
            result = await self.memory.consolidate(state["run_id"])
        except Exception as exc:  # learning is best-effort: the run's outcome is already saved
            log.warning("consolidation_failed", error=str(exc))
            return {
                "consolidation": {"error": str(exc)[:500]},
                "_summary": "memory consolidation failed (run kept)",
            }
        usage = result.usage.model_dump(mode="json")
        total = Usage.model_validate(merge_usage(state.get("usage"), usage))
        await self.memory.update_run(state["run_id"], RunUpdate(usage=total))
        return {
            "consolidation": {
                "summary": result.summary,
                "added": [g.id for g in result.added],
                "sharpened": [g.id for g in result.sharpened],
                "retired": [g.id for g in result.retired],
                "proposals": [p.id for p in result.proposals],
            },
            "usage": usage,
            "_summary": result.summary,
        }
