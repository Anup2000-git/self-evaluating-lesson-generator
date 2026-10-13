from evaluator_svc.checks.judges import Judge
from lessongen_common.llm import LLMProvider, LLMRole, LLMSettings
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import Verdict
from lessongen_common.testing import ScriptedChatModel

EX2 = load_seed_rubric().by_id("EX-2")
COV1 = load_seed_rubric().by_id("COV-1")


def _verdict(verdict: str, evidence: list[str] | None = None, fix: str = "") -> dict:
    return {
        "evidence": evidence or [],
        "reasoning": f"says {verdict}",
        "verdict": verdict,
        "fix_instruction": fix,
    }


def _judge(
    settings, judge=(), confirm=(), tiebreak=()
) -> tuple[Judge, dict[LLMRole, ScriptedChatModel]]:
    models = {
        LLMRole.JUDGE: ScriptedChatModel(model_name="mini", script=list(judge)),
        LLMRole.JUDGE_CONFIRM: ScriptedChatModel(model_name="mini-careful", script=list(confirm)),
        LLMRole.JUDGE_TIEBREAK: ScriptedChatModel(model_name="gpt-5.5", script=list(tiebreak)),
    }
    provider = LLMProvider(LLMSettings(_env_file=None), overrides=models)  # type: ignore[call-arg]
    return Judge(provider, settings), models


async def test_pass_needs_a_single_vote(settings, make_ctx) -> None:
    judge, models = _judge(settings, judge=[_verdict("PASS", ["open-book exam"])])
    result = await judge.judge(make_ctx(), EX2)
    assert result.verdict == Verdict.PASS and result.votes == []
    assert result.evidence_verified is True
    assert len(models[LLMRole.JUDGE].calls) == 1


async def test_fail_is_confirmed_by_a_second_vote(settings, make_ctx) -> None:
    judge, _ = _judge(
        settings,
        judge=[_verdict("FAIL", fix="Map the analogy parts.")],
        confirm=[_verdict("FAIL", fix="Add an explicit mapping table.")],
    )
    result = await judge.judge(make_ctx(), EX2)
    assert result.verdict == Verdict.FAIL
    assert [v.model for v in result.votes] == ["mini", "mini-careful"]
    assert result.fix_instruction == "Add an explicit mapping table."


async def test_disputed_fail_goes_to_the_tiebreaker(settings, make_ctx) -> None:
    judge, models = _judge(
        settings,
        judge=[_verdict("FAIL", fix="x")],
        confirm=[_verdict("PASS")],
        tiebreak=[_verdict("PASS")],
    )
    result = await judge.judge(make_ctx(), EX2)
    assert result.verdict == Verdict.PASS  # 2 of 3 votes say PASS
    assert result.fix_instruction == ""
    assert len(result.votes) == 3 and result.details["decided_by"] == "gpt-5.5"
    assert len(models[LLMRole.JUDGE_TIEBREAK].calls) == 1


async def test_fabricated_evidence_triggers_a_rejudgment(settings, make_ctx) -> None:
    judge, models = _judge(
        settings,
        judge=[
            _verdict("PASS", ["The lesson compares RAG to a cricket umpire reviewing a decision"]),
            _verdict("PASS", ["In an open-book exam, you first find the right page in your book."]),
        ],
    )
    result = await judge.judge(make_ctx(), EX2)
    assert result.evidence_verified is True
    retry_prompt = str(models[LLMRole.JUDGE].calls[1][-1].content)
    assert "does not appear in the lesson" in retry_prompt and "cricket umpire" in retry_prompt


async def test_prompts_fill_topic_placeholders_and_share_a_cacheable_prefix(
    settings, make_ctx
) -> None:
    judge, models = _judge(settings, judge=[_verdict("PASS"), _verdict("PASS")])
    ctx = make_ctx()
    await judge.judge(ctx, COV1)
    await judge.judge(ctx, EX2)
    first, second = models[LLMRole.JUDGE].calls
    assert first[:2] == second[:2]  # identical prefix -> prompt caching
    check_prompt = str(first[-1].content)
    assert "{topic_title}" not in check_prompt and "{what}" not in check_prompt
    assert "Introduction to RAG" in check_prompt
    assert "<lesson>" in str(first[1].content)
