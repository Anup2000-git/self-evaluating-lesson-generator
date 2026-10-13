"""Deterministic checks: the clean sample passes all nine; each fault trips the expected ones."""

import pytest

from evaluator_svc.checks.deterministic import REGISTRY, run_deterministic
from evaluator_svc.faults import apply_fault
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import CheckMethod, CheckResult, Verdict
from lessongen_common.testing import sample_lesson

DETERMINISTIC = load_seed_rubric().of_method(CheckMethod.DETERMINISTIC)


def _run_all(ctx) -> dict[str, CheckResult]:
    return {spec.id: run_deterministic(ctx, spec) for spec in DETERMINISTIC}


def test_every_rubric_impl_is_registered() -> None:
    assert {s.impl for s in DETERMINISTIC} <= set(REGISTRY)


def test_clean_sample_lesson_passes_all_deterministic_checks(make_ctx) -> None:
    results = _run_all(make_ctx())
    failures = {cid: r.reasoning for cid, r in results.items() if r.verdict == Verdict.FAIL}
    assert failures == {}


@pytest.mark.parametrize(
    ("fault_id", "must_fail"),
    [
        ("unexplained_jargon", {"JAR-1", "JAR-3"}),
        ("complex_language", {"LANG-2", "LANG-3"}),
        ("remove_example", {"FLOW-1"}),
        ("broken_flow", {"FLOW-1"}),
        ("missing_hindi_hints", {"JAR-4"}),
    ],
)
def test_faults_are_caught_by_code_checks(make_ctx, fault_id: str, must_fail: set[str]) -> None:
    lesson = apply_fault(sample_lesson(), fault_id).lesson
    results = _run_all(make_ctx(lesson))
    failed = {cid for cid, r in results.items() if r.verdict == Verdict.FAIL}
    assert must_fail <= failed, {cid: results[cid].reasoning for cid in must_fail}
    for cid in must_fail:
        assert results[cid].fix_instruction, cid


def test_jargon_check_explains_what_is_missing(make_ctx) -> None:
    lesson = apply_fault(sample_lesson(), "unexplained_jargon").lesson
    ctx = make_ctx(lesson)
    jar1 = run_deterministic(ctx, load_seed_rubric().by_id("JAR-1"))
    jar3 = run_deterministic(ctx, load_seed_rubric().by_id("JAR-3"))
    assert "cosine similarity" in jar1.details["missing"]
    assert jar3.details["unexpanded"] == ["HNSW"]
    assert "HNSW" in jar3.evidence[0]


def test_quiz_and_length_problems(make_ctx) -> None:
    lesson = sample_lesson()
    lesson.quiz = lesson.quiz[:2]
    lesson.quiz[0].options = ["A", "A", "B"]
    lesson.sections = lesson.sections[:2]
    results = _run_all(make_ctx(lesson))
    assert results["FLOW-3"].verdict == Verdict.FAIL
    assert "duplicate options" in results["FLOW-3"].reasoning
    assert results["LANG-5"].verdict == Verdict.FAIL
    assert "too short" in results["LANG-5"].fix_instruction


def test_readability_fails_for_academic_text(make_ctx) -> None:
    lesson = sample_lesson()
    for section in lesson.sections:
        section.body_markdown = (
            "Notwithstanding considerable architectural sophistication, retrieval-augmented "
            "methodologies fundamentally necessitate comprehensive infrastructural "
            "considerations regarding computational scalability. "
        ) * 40
    result = run_deterministic(make_ctx(lesson), load_seed_rubric().by_id("LANG-1"))
    assert result.verdict == Verdict.FAIL
    assert result.details["fk_grade"] > 8


def test_capitalised_emphasis_is_not_an_acronym(make_ctx) -> None:
    lesson = sample_lesson()
    lesson.sections[1].body_markdown += "\n\nRAG does NOT change the model."
    result = run_deterministic(make_ctx(lesson), load_seed_rubric().by_id("JAR-3"))
    assert result.verdict == Verdict.PASS
