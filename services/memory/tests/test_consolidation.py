from lessongen_common.llm import LLMProvider, LLMRole, LLMSettings
from lessongen_common.schemas import (
    CheckOverride,
    EffectivenessUpdate,
    FeedbackCreate,
    GuidelineOrigin,
    GuidelineStatus,
    GuidelineTarget,
    ProposalKind,
    Verdict,
)
from lessongen_common.testing import ScriptedChatModel
from memory_svc.consolidation import Consolidator, ReflectionOutput, failure_episodes
from memory_svc.repository import MemoryRepository
from memory_svc.settings import MemorySettings


def _consolidator(
    repo: MemoryRepository, settings: MemorySettings, *script: object
) -> tuple[Consolidator, ScriptedChatModel]:
    model = ScriptedChatModel(model_name="reflector", script=list(script))
    provider = LLMProvider(LLMSettings(_env_file=None), overrides={LLMRole.REFLECTOR: model})  # type: ignore[call-arg]
    return Consolidator(repo, provider, settings), model


async def test_failure_episodes_capture_what_fixed_each_failure(
    repo, make_attempt, finish_run
) -> None:
    await finish_run(
        repo,
        "r1",
        [
            make_attempt(1, ["JAR-2", "EX-1"]),
            make_attempt(2, ["EX-1"], [("JAR-2", "Defined chunk first")]),
            make_attempt(3, []),
        ],
    )
    episodes = failure_episodes(await repo.get_run("r1"))
    by_key = {(e["attempt"], e["check_id"]): e for e in episodes}
    assert by_key[(1, "JAR-2")]["fixed_by"] == "Defined chunk first"
    assert by_key[(1, "EX-1")]["fixed_by"] == ""  # still failing on attempt 2
    assert by_key[(2, "EX-1")]["fixed_by"] == "a revision (no note given)"


async def test_consolidation_learns_guidelines_and_tracks_effectiveness(
    repo, settings, make_attempt, finish_run
) -> None:
    existing = await repo.add_guideline(
        topic_id="rag",
        text="Use an Indian analogy for RAG.",
        check_ids=["EX-2"],
        target=GuidelineTarget.WRITER,
        origin=GuidelineOrigin.FAILURE,
        created_from_run=None,
        reason="seed",
    )
    await finish_run(
        repo,
        "r1",
        [
            make_attempt(1, ["JAR-2"]),
            make_attempt(2, [], [("JAR-2", "Explained 'embedding' before using it")]),
        ],
        guidelines=[existing.id],
    )
    reflection = ReflectionOutput(
        new_guidelines=[
            {
                "text": "Before using the word 'embedding', explain it as a list of numbers that captures meaning.",
                "check_ids": ["JAR-2", "NOT-A-REAL-CHECK"],
                "target": "writer",
                "source": "failure",
                "rationale": "JAR-2 failed because 'embedding' was used before being explained.",
            }
        ],
        sharpen=[],
        retire=[],
    )
    consolidator, model = _consolidator(repo, settings, reflection)
    result = await consolidator.consolidate("r1")

    assert [e.outcome for e in result.effectiveness] == ["helped"]  # EX-2 passed on attempt 1
    assert len(result.added) == 1
    assert result.added[0].check_ids == ["JAR-2"]  # unknown check ids are dropped
    prompt = model.calls[0][1].content
    assert "JAR-2" in prompt and "Explained 'embedding' before using it" in prompt
    seeded = await repo.get_guideline(existing.id)
    assert (seeded.times_applied, seeded.times_helped) == (1, 1)
    assert (await repo.get_run("r1")).model_dump().get("id") == "r1"
    assert "1 new guideline" in result.summary


async def test_first_attempt_success_skips_the_llm(
    repo, settings, make_attempt, finish_run
) -> None:
    await finish_run(repo, "r1", [make_attempt(1, [])])
    consolidator, model = _consolidator(repo, settings)  # empty script: any LLM call would fail
    result = await consolidator.consolidate("r1")
    assert model.calls == []
    assert "first attempt passed" in result.summary


async def test_near_duplicate_guideline_is_merged_not_added(
    repo, settings, make_attempt, finish_run
) -> None:
    existing = await repo.add_guideline(
        topic_id="rag",
        text="Explain the word embedding before you use it.",
        check_ids=["JAR-2"],
        target=GuidelineTarget.WRITER,
        origin=GuidelineOrigin.FAILURE,
        created_from_run=None,
        reason="seed",
    )
    await finish_run(repo, "r1", [make_attempt(1, ["JAR-2"]), make_attempt(2, [])])
    reflection = ReflectionOutput(
        new_guidelines=[
            {
                "text": "Explain the word embedding before you use it in the lesson.",
                "check_ids": ["JAR-2"],
                "target": "writer",
                "source": "failure",
                "rationale": "again",
            }
        ],
        sharpen=[],
        retire=[],
    )
    consolidator, _ = _consolidator(repo, settings, reflection)
    result = await consolidator.consolidate("r1")
    assert result.added == []
    assert [g.id for g in result.sharpened] == [existing.id]
    assert (await repo.get_guideline(existing.id)).version == 2


async def test_guardrails_retire_ineffective_guidelines_and_escalate(
    repo, settings, make_attempt, finish_run
) -> None:
    stubborn = await repo.add_guideline(
        topic_id="rag",
        text="Keep sentences short.",
        check_ids=["LANG-2"],
        target=GuidelineTarget.WRITER,
        origin=GuidelineOrigin.FAILURE,
        created_from_run=None,
        reason="seed",
    )
    await repo.record_effectiveness(
        [EffectivenessUpdate(guideline_id=stubborn.id, check_ids=["LANG-2"], outcome="missed")] * 3
    )
    for i in range(3):
        await finish_run(repo, f"r{i}", [make_attempt(1, ["LANG-2"]), make_attempt(2, [])])
    empty = ReflectionOutput(new_guidelines=[], sharpen=[], retire=[])
    consolidator, _ = _consolidator(repo, settings, empty)
    result = await consolidator.consolidate("r2")

    assert stubborn.id in {g.id for g in result.retired}
    assert (await repo.get_guideline(stubborn.id)).status == GuidelineStatus.RETIRED
    escalations = [p for p in result.proposals if p.source == "escalation"]
    assert [p.check_id for p in escalations] == ["LANG-2"]
    assert escalations[0].kind == ProposalKind.PROMPT_CHANGE


async def test_human_override_becomes_a_rubric_clarification_proposal(
    repo, settings, make_attempt, finish_run
) -> None:
    await finish_run(repo, "r1", [make_attempt(1, ["EX-2"]), make_attempt(2, ["EX-2"])])
    await repo.add_feedback(
        FeedbackCreate(
            run_id="r1",
            rating="up",
            check_overrides=[
                CheckOverride(
                    check_id="EX-2",
                    human_verdict=Verdict.PASS,
                    note="The Diwali analogy is very Indian.",
                )
            ],
        )
    )
    clarification = {
        "title": "Treat festival analogies as everyday Indian life",
        "add_notes": [
            "Analogies about Indian festivals (Diwali, Holi) count as everyday Indian life."
        ],
        "add_pass_criteria": [],
        "add_fail_criteria": [],
        "rationale": "The reviewer judged the festival analogy familiar to the audience.",
    }
    consolidator, _ = _consolidator(
        repo, settings, ReflectionOutput(new_guidelines=[], sharpen=[], retire=[]), clarification
    )
    result = await consolidator.consolidate("r1")

    proposals = [p for p in result.proposals if p.kind == ProposalKind.CLARIFY_CHECK]
    assert len(proposals) == 1 and proposals[0].check_id == "EX-2"
    assert proposals[0].status.value == "pending"  # the rubric is NOT changed automatically
    assert (await repo.active_rubric()).version == 1
    assert result.feedback_processed == 1
    assert (await repo.list_feedback(processed=False)) == []


async def test_without_azure_the_deterministic_parts_still_run(
    repo, settings, make_attempt, finish_run
) -> None:
    await finish_run(repo, "r1", [make_attempt(1, ["JAR-2"]), make_attempt(2, [])])
    unconfigured = Consolidator(repo, LLMProvider(LLMSettings(_env_file=None)), settings)  # type: ignore[call-arg]
    result = await unconfigured.consolidate("r1")
    assert "reflection skipped" in result.summary
