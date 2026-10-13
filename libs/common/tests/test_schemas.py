from collections import Counter

import pytest
from pydantic import ValidationError

from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import (
    CheckMethod,
    Dimension,
    RunMode,
    RunRequest,
    SectionKind,
    validate_lesson_contract,
)
from lessongen_common.testing import sample_lesson


def test_sample_lesson_satisfies_contract() -> None:
    assert validate_lesson_contract(sample_lesson()) == []


def test_contract_reports_missing_and_out_of_order_sections() -> None:
    lesson = sample_lesson()
    sections = [s for s in lesson.sections if s.kind != SectionKind.EXAMPLE]
    how = next(s for s in sections if s.kind == SectionKind.HOW)
    sections.remove(how)
    sections.insert(0, how)
    lesson.sections = sections
    problems = {p.problem for p in validate_lesson_contract(lesson)}
    assert "missing a 'example' section" in problems
    assert any("out of teaching order" in p for p in problems)


def test_contract_reports_quiz_problems() -> None:
    lesson = sample_lesson()
    lesson.quiz[0].correct_option_index = 9
    lesson.quiz[1].options = ["same", "Same", "other"]
    fields = {p.field for p in validate_lesson_contract(lesson)}
    assert "quiz[0].correct_option_index" in fields
    assert "quiz[1].options" in fields


def test_seed_rubric_has_23_binary_checks_across_all_dimensions() -> None:
    rubric = load_seed_rubric()
    assert rubric.version == 1
    assert len(rubric.checks) == 23
    assert {c.dimension for c in rubric.checks} == set(Dimension)
    methods = Counter(c.method for c in rubric.checks)
    assert methods == {
        CheckMethod.DETERMINISTIC: 9,
        CheckMethod.LLM_JUDGE: 11,
        CheckMethod.FACT_CHECK: 2,
        CheckMethod.LEARNER: 1,
    }
    assert all(c.judge for c in rubric.of_method(CheckMethod.LLM_JUDGE))


def test_run_request_validates_mode_and_lesson() -> None:
    RunRequest(topic="Introduction to RAG")
    RunRequest(topic="RAG", mode=RunMode.REPAIR, initial_lesson=sample_lesson())
    with pytest.raises(ValidationError):
        RunRequest(topic="RAG", mode=RunMode.EVALUATE_ONLY)
    with pytest.raises(ValidationError):
        RunRequest(topic="RAG", initial_lesson=sample_lesson())
    with pytest.raises(ValidationError):
        RunRequest(topic="RAG", max_retries=3)
