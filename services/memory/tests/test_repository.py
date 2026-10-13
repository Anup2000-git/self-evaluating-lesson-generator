import pytest

from lessongen_common.errors import LessongenError, NotFoundError
from lessongen_common.schemas import (
    EffectivenessUpdate,
    FeedbackCreate,
    GuidelineOrigin,
    GuidelineStatus,
    GuidelineTarget,
    GuidelineUpdate,
    ProposalKind,
    RunCreate,
    RunMode,
)
from memory_svc.repository import MemoryRepository


async def _guideline(repo: MemoryRepository, text: str, check: str, topic: str = "rag"):
    return await repo.add_guideline(
        topic_id=topic,
        text=text,
        check_ids=[check],
        target=GuidelineTarget.WRITER,
        origin=GuidelineOrigin.FAILURE,
        created_from_run=None,
        reason="test",
    )


async def test_create_run_is_idempotent(repo: MemoryRepository) -> None:
    create = RunCreate(
        id="run_a",
        topic="RAG",
        topic_id="rag",
        mode=RunMode.GENERATE,
        max_retries=2,
        helper_language="Hindi",
    )
    first = await repo.create_run(create)
    again = await repo.create_run(create)
    assert first.id == again.id == "run_a"
    assert (await repo.list_runs()).total == 1


async def test_attempts_are_upserted_and_form_the_rejection_log(
    repo: MemoryRepository, make_attempt, finish_run
) -> None:
    fixed = make_attempt(2, [], [("JAR-2", "Explained embedding first")])
    await finish_run(repo, "run_b", [make_attempt(1, ["JAR-2", "EX-1"]), fixed])
    await repo.save_attempt("run_b", fixed)  # a resumed run re-saving is harmless
    detail = await repo.get_run("run_b")
    assert [a.attempt_no for a in detail.attempts] == [1, 2]
    assert detail.attempts[0].evaluation.failed_check_ids == ["EX-1", "JAR-2"]
    assert detail.attempts[1].revision_notes[0].check_id == "JAR-2"
    assert detail.attempts_count == 2 and detail.final_attempt_no == 2
    assert detail.status.value == "shipped"
    with pytest.raises(NotFoundError):
        await repo.get_run("missing")


async def test_memory_context_ranks_guidelines_and_reports_frequent_failures(
    repo: MemoryRepository, make_attempt, finish_run
) -> None:
    good = await _guideline(repo, "Explain embeddings before using them.", "JAR-2")
    weak = await _guideline(repo, "Use an Indian analogy.", "EX-2")
    other_topic = await _guideline(repo, "Irrelevant.", "X", topic="other")
    await repo.record_effectiveness(
        [
            EffectivenessUpdate(guideline_id=good.id, check_ids=["JAR-2"], outcome="helped"),
            EffectivenessUpdate(guideline_id=weak.id, check_ids=["EX-2"], outcome="missed"),
        ]
    )
    await finish_run(repo, "r1", [make_attempt(1, ["EX-2"]), make_attempt(2, [])])
    await finish_run(repo, "r2", [make_attempt(1, ["EX-2", "LANG-1"]), make_attempt(2, [])])
    await finish_run(repo, "r3", [make_attempt(1, [])])

    context = await repo.memory_context("rag")
    assert [g.id for g in context.guidelines] == [good.id, weak.id]
    assert other_topic.id not in {g.id for g in context.guidelines}
    rates = {f.check_id: f.first_attempt_fail_rate for f in context.frequent_failures}
    assert rates == {
        "EX-2": pytest.approx(0.667, abs=0.001),
        "LANG-1": pytest.approx(0.333, abs=0.001),
    }


async def test_guideline_edits_are_versioned(repo: MemoryRepository) -> None:
    g = await _guideline(repo, "v1 text", "JAR-2")
    g = await repo.update_guideline(g.id, GuidelineUpdate(text="v2 text", reason="sharpened"))
    g = await repo.update_guideline(
        g.id, GuidelineUpdate(status=GuidelineStatus.RETIRED, reason="dup")
    )
    assert g.version == 2 and g.status == GuidelineStatus.RETIRED
    assert [h.text for h in g.history] == ["v1 text", "v2 text", "v2 text"]
    assert g.history[-1].reason.startswith("retired")


async def test_feedback_requires_existing_run(
    repo: MemoryRepository, make_attempt, finish_run
) -> None:
    with pytest.raises(NotFoundError):
        await repo.add_feedback(FeedbackCreate(run_id="nope", rating="up"))
    await finish_run(repo, "r1", [make_attempt(1, [])])
    fb = await repo.add_feedback(
        FeedbackCreate(run_id="r1", rating="down", comment="Too many long words")
    )
    assert not fb.processed
    assert (await repo.memory_context("rag")).human_notes == ["Too many long words"]


async def test_approved_clarification_creates_new_rubric_version(repo: MemoryRepository) -> None:
    proposal = await repo.create_proposal(
        check_id="EX-2",
        kind=ProposalKind.CLARIFY_CHECK,
        title="Count festival analogies as Indian",
        proposed_change={
            "check_id": "EX-2",
            "add_notes": ["Festivals like Diwali count as everyday Indian life."],
        },
        rationale="Reviewer disagreed",
        evidence=[],
        source="feedback",
    )
    decided = await repo.decide_proposal(proposal.id, approve=True, note="ok")
    assert decided.resulting_version == 2
    active = await repo.active_rubric()
    assert active.version == 2 and active.created_by == "human-approved-proposal"
    assert "Diwali" in active.rubric.by_id("EX-2").judge.notes[-1]  # type: ignore[union-attr]
    assert [v.status for v in await repo.list_rubric_versions()] == ["active", "superseded"]
    with pytest.raises(LessongenError):
        await repo.decide_proposal(proposal.id, approve=False, note="")


async def test_stats_track_first_pass_rate(
    repo: MemoryRepository, make_attempt, finish_run
) -> None:
    await finish_run(repo, "r1", [make_attempt(1, ["EX-1"]), make_attempt(2, [])])
    await finish_run(repo, "r2", [make_attempt(1, [])], guidelines=["G-x"])
    stats = await repo.stats("rag")
    assert stats.runs_total == 2 and stats.runs_shipped == 2
    assert stats.first_pass_rate == 0.5
    assert stats.avg_attempts == 1.5
    assert [p.first_attempt_passed for p in stats.trend] == [False, True]
    assert stats.trend[1].guidelines_applied == 1
