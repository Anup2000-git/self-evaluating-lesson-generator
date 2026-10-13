"""End-to-end behaviour of the LangGraph loop against in-memory fakes of every service."""

import pytest

from lessongen_common.schemas import RunMode, RunStatus
from orchestrator_svc.graph.pipeline import RunCancelled, initial_state


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 40}


async def _run(graph, job):
    return await graph.ainvoke(initial_state(job), _config(job.run_id))


async def test_ships_on_first_attempt(
    make_pipeline, evaluator_factory, fakes, job_factory, bus
) -> None:
    graph, _ = make_pipeline(evaluator_factory([[]]))
    final = await _run(graph, job_factory())
    assert final["status"] == RunStatus.SHIPPED.value
    assert final["final_attempt_no"] == 1
    assert [a["kind"] for a in final["attempts"]] == ["initial"]
    assert fakes["generator"].calls == ["plan", "write"]
    memory = fakes["memory"]
    assert memory.consolidated == ["run_t"]
    assert memory.runs["run_t"].guideline_ids_applied == ["G-1"]
    assert memory.runs["run_t"].status == RunStatus.SHIPPED
    nodes = [d["node"] for _, t, d in bus.events if t == "node.started"]
    assert nodes == ["recall_memory", "plan", "write", "evaluate", "finalize", "consolidate_memory"]
    assert final["usage"]["cost_usd"] > 0


async def test_revises_then_ships_with_a_rejection_log(
    make_pipeline, evaluator_factory, fakes, job_factory, bus
) -> None:
    graph, _ = make_pipeline(evaluator_factory([["JAR-2", "EX-1"], []]))
    final = await _run(graph, job_factory())
    assert final["status"] == RunStatus.SHIPPED.value and final["final_attempt_no"] == 2
    first, second = final["attempts"]
    assert first["evaluation"]["failed_check_ids"] == ["EX-1", "JAR-2"]
    assert second["kind"] == "patch"
    assert {n["check_id"] for n in second["revision_notes"]} == {"EX-1", "JAR-2"}
    assert "patch: 2 of 23" in second["strategy_reason"]
    assert {d["kind"]: d["change"] for d in second["diff"]}["how"] == "modified"
    assert fakes["generator"].calls[2] == ("revise", "patch", ["EX-1", "JAR-2"], True)
    rejected = [d for _, t, d in bus.events if t == "attempt.rejected"]
    assert rejected[0]["next"] == "revise"
    stored = fakes["memory"].attempts["run_t"]
    assert sorted(stored) == [1, 2]


async def test_escalates_to_a_human_after_max_retries(
    make_pipeline, evaluator_factory, fakes, job_factory
) -> None:
    graph, _ = make_pipeline(evaluator_factory([["ACC-1", "EX-1"], ["EX-1"], ["EX-1", "LANG-2"]]))
    final = await _run(graph, job_factory())
    assert len(final["attempts"]) == 3  # first try + 2 retries: the loop always terminates
    assert final["status"] == RunStatus.NEEDS_HUMAN_REVIEW.value
    assert final["final_attempt_no"] == 2  # fewest failures, no critical ones
    assert "max retries reached (2)" in final["status_reason"]
    assert fakes["memory"].consolidated == ["run_t"]  # we still learn from failed runs


async def test_rewrites_when_too_much_failed(
    make_pipeline, evaluator_factory, fakes, job_factory
) -> None:
    many = ["EX-1", "EX-2", "JAR-1", "JAR-2", "COV-1", "COV-2", "FLOW-2"]
    graph, _ = make_pipeline(evaluator_factory([many, []]))
    final = await _run(graph, job_factory())
    assert final["attempts"][1]["kind"] == "rewrite"
    assert fakes["generator"].calls[2][1] == "rewrite"


async def test_evaluate_only_mode(make_pipeline, evaluator_factory, fakes, job_factory) -> None:
    evaluator = evaluator_factory([["ACC-1"]])
    graph, _ = make_pipeline(evaluator)
    final = await _run(graph, job_factory(mode=RunMode.EVALUATE_ONLY, lesson=True, max_retries=0))
    assert final["status"] == RunStatus.EVALUATED.value
    assert [a["kind"] for a in final["attempts"]] == ["provided"]
    assert fakes["generator"].calls == [] and evaluator.calls == 1
    assert fakes["memory"].consolidated == []


async def test_repair_mode_fixes_a_provided_lesson(
    make_pipeline, evaluator_factory, fakes, job_factory
) -> None:
    graph, _ = make_pipeline(evaluator_factory([["ACC-1"], []]))
    final = await _run(graph, job_factory(mode=RunMode.REPAIR, lesson=True))
    assert [a["kind"] for a in final["attempts"]] == ["provided", "patch"]
    assert final["status"] == RunStatus.SHIPPED.value
    assert fakes["generator"].calls == [
        ("revise", "patch", ["ACC-1"], False)
    ]  # no plan in repair mode


async def test_budget_cap_stops_retries(make_pipeline, evaluator_factory, job_factory) -> None:
    graph, _ = make_pipeline(evaluator_factory([["EX-1"], []]), budget=0.1)
    final = await _run(graph, job_factory())
    assert len(final["attempts"]) == 1
    assert final["status"] == RunStatus.NEEDS_HUMAN_REVIEW.value
    assert "budget exhausted" in final["status_reason"]


async def test_evaluation_errors_are_retried_without_rewriting(
    make_pipeline, evaluator_factory, fakes, job_factory
) -> None:
    evaluator = evaluator_factory([{"failed": ["FLOW-2"], "errors": ["FLOW-2"]}, []])
    graph, _ = make_pipeline(evaluator)
    final = await _run(graph, job_factory())
    assert evaluator.calls == 2
    assert len(final["attempts"]) == 1 and final["attempts"][0]["evaluation"]["passed"] is True
    assert fakes["generator"].calls == ["plan", "write"]
    assert final["status"] == RunStatus.SHIPPED.value


async def test_cancellation_stops_before_the_next_node(
    make_pipeline, evaluator_factory, job_factory
) -> None:
    graph, _ = make_pipeline(evaluator_factory([[]]), cancelled={"run_t"})
    with pytest.raises(RunCancelled):
        await _run(graph, job_factory())


async def test_resumes_from_checkpoint_after_a_crash(
    make_pipeline, evaluator_factory, fakes, job_factory
) -> None:
    evaluator = evaluator_factory([RuntimeError("evaluator container restarted"), []])
    graph, _ = make_pipeline(evaluator)
    job = job_factory()
    with pytest.raises(RuntimeError):
        await _run(graph, job)
    snapshot = await graph.aget_state(_config(job.run_id))
    assert snapshot.next == ("evaluate",)  # plan + write are safely checkpointed
    final = await graph.ainvoke(None, _config(job.run_id))
    assert final["status"] == RunStatus.SHIPPED.value
    assert fakes["generator"].calls == ["plan", "write"]  # nothing was regenerated
