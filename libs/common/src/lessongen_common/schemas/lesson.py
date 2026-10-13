"""Lesson contracts shared by the generator (producer), evaluator (consumer) and UI.

LLM-facing models here deliberately avoid defaults, dict fields and JSON-schema
constraints (minItems, pattern, ...): Azure/OpenAI strict structured outputs require
every property to be required and reject several keywords. Business rules such as
"3-5 quiz questions" are enforced in code (see ``validate_lesson_contract``) so the
error can be fed back to the agent for self-correction.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SectionKind(StrEnum):
    HOOK = "hook"
    WHAT = "what"
    WHY = "why"
    HOW = "how"
    EXAMPLE = "example"
    MISCONCEPTIONS = "misconceptions"
    SUMMARY = "summary"


# Teaching order every lesson must follow. HOOK and MISCONCEPTIONS are optional.
TEACHING_ORDER: tuple[SectionKind, ...] = (
    SectionKind.HOOK,
    SectionKind.WHAT,
    SectionKind.WHY,
    SectionKind.HOW,
    SectionKind.EXAMPLE,
    SectionKind.MISCONCEPTIONS,
    SectionKind.SUMMARY,
)
REQUIRED_SECTIONS: tuple[SectionKind, ...] = (
    SectionKind.WHAT,
    SectionKind.WHY,
    SectionKind.HOW,
    SectionKind.EXAMPLE,
    SectionKind.SUMMARY,
)


class Section(BaseModel):
    kind: SectionKind = Field(description="Pedagogical role of this section.")
    heading: str = Field(description="Short, friendly heading in simple English.")
    body_markdown: str = Field(
        description="Section text in Markdown. Short sentences, simple words, Hindi hints in brackets."
    )


class GlossaryEntry(BaseModel):
    term: str = Field(description="The English term exactly as used in the lesson.")
    simple_meaning: str = Field(description="One short sentence in very simple English.")
    helper_meaning: str = Field(
        description="Meaning in the learner's helper language (e.g. Hindi in Devanagari script)."
    )


class QuizQuestion(BaseModel):
    question: str
    options: list[str] = Field(description="3 or 4 answer options.")
    correct_option_index: int = Field(description="0-based index of the single correct option.")
    explanation: str = Field(description="Why the correct option is right, in simple English.")


class Lesson(BaseModel):
    title: str
    learning_objectives: list[str] = Field(description="3-4 'You will be able to...' outcomes.")
    sections: list[Section]
    glossary: list[GlossaryEntry]
    quiz: list[QuizQuestion]

    def section(self, kind: SectionKind) -> Section | None:
        return next((s for s in self.sections if s.kind == kind), None)

    def body_markdown(self) -> str:
        """All section text in order - what the learner actually reads as 'the lesson'."""
        parts = [f"## {s.heading}\n\n{s.body_markdown}" for s in self.sections]
        return "\n\n".join(parts)


class PlannedSection(BaseModel):
    kind: SectionKind
    heading: str
    key_points: list[str] = Field(description="Facts/ideas this section must teach, in order.")
    terms_to_define: list[str] = Field(description="Technical terms first introduced here.")


class LessonPlan(BaseModel):
    title: str
    learning_objectives: list[str]
    analogy: str = Field(
        description="One everyday-India analogy and how each of its parts maps to the topic's parts."
    )
    worked_example: str = Field(
        description="Scenario for the end-to-end worked example (question, data, steps, answer)."
    )
    sections: list[PlannedSection]
    glossary_terms: list[str]
    quiz_focus: list[str] = Field(description="Ideas the quiz should test.")


class RevisionNote(BaseModel):
    check_id: str = Field(description="Rubric check id this change addresses, e.g. JAR-2.")
    change: str = Field(description="What you changed and where, in one or two sentences.")


class LessonRevision(BaseModel):
    lesson: Lesson
    revision_notes: list[RevisionNote]


class ContractViolation(BaseModel):
    field: str
    problem: str


def validate_lesson_contract(lesson: Lesson) -> list[ContractViolation]:
    """Structural rules every lesson must satisfy before it is even worth evaluating.

    These mirror the deterministic rubric checks FLOW-1 / FLOW-3 so the writer agent can
    fix contract problems itself instead of wasting a full evaluation round.
    """
    problems: list[ContractViolation] = []
    kinds = [s.kind for s in lesson.sections]
    for required in REQUIRED_SECTIONS:
        if required not in kinds:
            problems.append(
                ContractViolation(field="sections", problem=f"missing a '{required}' section")
            )
    first_index = {k: kinds.index(k) for k in TEACHING_ORDER if k in kinds}
    ordered = sorted(first_index, key=lambda k: first_index[k])
    expected = [k for k in TEACHING_ORDER if k in first_index]
    if ordered != expected:
        problems.append(
            ContractViolation(
                field="sections",
                problem="sections are out of teaching order; expected "
                + " -> ".join(k.value for k in expected),
            )
        )
    for i, s in enumerate(lesson.sections):
        if not s.body_markdown.strip():
            problems.append(ContractViolation(field=f"sections[{i}]", problem="empty body"))
    if not 3 <= len(lesson.learning_objectives) <= 5:
        problems.append(
            ContractViolation(field="learning_objectives", problem="need 3 to 5 objectives")
        )
    if not lesson.glossary:
        problems.append(ContractViolation(field="glossary", problem="glossary is empty"))
    if not 3 <= len(lesson.quiz) <= 5:
        problems.append(ContractViolation(field="quiz", problem="need 3 to 5 questions"))
    for i, q in enumerate(lesson.quiz):
        if not 3 <= len(q.options) <= 4:
            problems.append(
                ContractViolation(field=f"quiz[{i}].options", problem="need 3 or 4 options")
            )
        if not 0 <= q.correct_option_index < len(q.options):
            problems.append(
                ContractViolation(
                    field=f"quiz[{i}].correct_option_index", problem="index out of range"
                )
            )
        if len({o.strip().lower() for o in q.options}) != len(q.options):
            problems.append(
                ContractViolation(field=f"quiz[{i}].options", problem="duplicate options")
            )
        if not q.explanation.strip():
            problems.append(
                ContractViolation(field=f"quiz[{i}].explanation", problem="missing explanation")
            )
    return problems
