import pytest

from evaluator_svc.faults import FAULTS, apply_fault, list_faults
from lessongen_common.errors import NotFoundError
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import SectionKind, validate_lesson_contract
from lessongen_common.testing import sample_lesson


def test_every_fault_targets_real_checks() -> None:
    check_ids = {c.id for c in load_seed_rubric().checks}
    for info in list_faults():
        assert info.expected_checks and set(info.expected_checks) <= check_ids, info.id


@pytest.mark.parametrize("fault_id", sorted(FAULTS))
def test_faults_change_the_lesson_without_mutating_the_original(fault_id: str) -> None:
    original = sample_lesson()
    before = original.model_dump_json()
    applied = apply_fault(original, fault_id)
    assert original.model_dump_json() == before
    assert applied.lesson.model_dump_json() != before
    assert applied.fault.id == fault_id


def test_specific_fault_effects() -> None:
    lesson = sample_lesson()
    assert (
        "retrained on your documents"
        in apply_fault(lesson, "factual_error").lesson.section(SectionKind.HOW).body_markdown
    )
    assert apply_fault(lesson, "remove_example").lesson.section(SectionKind.EXAMPLE) is None
    kinds = [s.kind for s in apply_fault(lesson, "broken_flow").lesson.sections]
    assert kinds.index(SectionKind.HOW) < kinds.index(SectionKind.WHAT)
    wrong = apply_fault(lesson, "wrong_hindi_hint").lesson
    assert any(g.helper_meaning == "बिजली" for g in wrong.glossary)
    quiz = apply_fault(lesson, "wrong_quiz_answer").lesson.quiz[0]
    assert quiz.correct_option_index != lesson.quiz[0].correct_option_index
    # Faults that only change content keep the structural contract intact.
    assert validate_lesson_contract(apply_fault(lesson, "factual_error").lesson) == []


def test_unknown_fault_is_a_clear_error() -> None:
    with pytest.raises(NotFoundError):
        apply_fault(sample_lesson(), "nope")
