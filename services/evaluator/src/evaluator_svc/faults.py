"""Deliberate-error presets for the Evaluator Lab (and the evaluator's own test suite).

Each fault makes one realistic mistake and declares which checks *should* catch it, so the
Lab can show "expected vs caught" and the golden-set eval can measure detection rate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from lessongen_common.errors import NotFoundError
from lessongen_common.schemas import Lesson, SectionKind


class FaultInfo(BaseModel):
    id: str
    title: str
    category: str
    description: str
    injected_text: str
    expected_checks: list[str]


class FaultApplyRequest(BaseModel):
    lesson: Lesson
    fault_id: str


class FaultApplied(BaseModel):
    lesson: Lesson
    fault: FaultInfo


@dataclass(frozen=True)
class Fault:
    info: FaultInfo
    apply: Callable[[Lesson], Lesson]


def _section_index(lesson: Lesson, kind: SectionKind) -> int:
    for i, section in enumerate(lesson.sections):
        if section.kind == kind:
            return i
    return min(1, len(lesson.sections) - 1)


def _append(kind: SectionKind, text: str) -> Callable[[Lesson], Lesson]:
    def apply(lesson: Lesson) -> Lesson:
        out = lesson.model_copy(deep=True)
        i = _section_index(out, kind)
        out.sections[i].body_markdown = out.sections[i].body_markdown.rstrip() + "\n\n" + text
        return out

    return apply


FACTUAL_ERROR = (
    "Here is an important fact: in RAG, the language model is retrained on your documents "
    "every time you ask a question, so it remembers them forever."
)
INVENTED_STATISTIC = "RAG was invented by Google in 2015, and studies show that it makes AI answers 95% more accurate."
JARGON = (
    "Technically, the retriever runs approximate nearest neighbour search over dense embeddings "
    "with cosine similarity inside an HNSW index."
)
COMPLEX = (
    "Notwithstanding the multifarious considerations that inevitably accompany the deployment of "
    "sophisticated generative architectures, it is incumbent upon practitioners to recognise that "
    "retrieval-augmented paradigms, which judiciously amalgamate parametric and non-parametric "
    "knowledge repositories, constitute a quintessential mechanism for ameliorating the epistemic "
    "limitations intrinsic to large-scale language models."
)
WRONG_HINDI = "बिजली"


def _complex_language(lesson: Lesson) -> Lesson:
    out = lesson.model_copy(deep=True)
    i = _section_index(out, SectionKind.WHAT)
    paragraphs = out.sections[i].body_markdown.split("\n\n")
    paragraphs[0] = COMPLEX
    out.sections[i].body_markdown = "\n\n".join(paragraphs)
    return out


def _remove_example(lesson: Lesson) -> Lesson:
    out = lesson.model_copy(deep=True)
    out.sections = [s for s in out.sections if s.kind != SectionKind.EXAMPLE]
    return out


def _broken_flow(lesson: Lesson) -> Lesson:
    out = lesson.model_copy(deep=True)
    how = [s for s in out.sections if s.kind == SectionKind.HOW]
    rest = [s for s in out.sections if s.kind != SectionKind.HOW]
    insert_at = next((i for i, s in enumerate(rest) if s.kind == SectionKind.WHAT), 0)
    out.sections = rest[:insert_at] + how + rest[insert_at:]
    return out


def _wrong_hindi(lesson: Lesson) -> Lesson:
    out = lesson.model_copy(deep=True)
    target = next(
        (g for g in out.glossary if "retriev" in g.term.lower()),
        out.glossary[0] if out.glossary else None,
    )
    if target is not None:
        old = target.helper_meaning
        target.helper_meaning = WRONG_HINDI
        for section in out.sections:
            if old and old in section.body_markdown:
                section.body_markdown = section.body_markdown.replace(old, WRONG_HINDI)
    return out


def _wrong_quiz_answer(lesson: Lesson) -> Lesson:
    out = lesson.model_copy(deep=True)
    if out.quiz:
        q = out.quiz[0]
        q.correct_option_index = (q.correct_option_index + 1) % len(q.options)
    return out


def _remove_hindi(lesson: Lesson) -> Lesson:
    out = lesson.model_copy(deep=True)
    for entry in out.glossary[:3]:
        entry.helper_meaning = entry.simple_meaning
    return out


FAULTS: dict[str, Fault] = {
    f.info.id: f
    for f in [
        Fault(
            FaultInfo(
                id="factual_error",
                title="Factual error",
                category="accuracy",
                description="Adds a false claim to 'How it works': that RAG retrains the model on every question.",
                injected_text=FACTUAL_ERROR,
                expected_checks=["ACC-1"],
            ),
            _append(SectionKind.HOW, FACTUAL_ERROR),
        ),
        Fault(
            FaultInfo(
                id="invented_statistic",
                title="Invented history and statistic",
                category="accuracy",
                description="Adds a made-up origin (Google, 2015) and a fake '95% more accurate' statistic.",
                injected_text=INVENTED_STATISTIC,
                expected_checks=["ACC-1", "ACC-2"],
            ),
            _append(SectionKind.WHY, INVENTED_STATISTIC),
        ),
        Fault(
            FaultInfo(
                id="unexplained_jargon",
                title="Unexplained jargon",
                category="jargon",
                description="Adds a sentence full of unexplained technical terms and an unexpanded acronym (HNSW).",
                injected_text=JARGON,
                expected_checks=["JAR-1", "JAR-2", "JAR-3"],
            ),
            _append(SectionKind.HOW, JARGON),
        ),
        Fault(
            FaultInfo(
                id="complex_language",
                title="Academic, complex language",
                category="language",
                description="Replaces the opening of 'What is it' with one very long, academic sentence.",
                injected_text=COMPLEX,
                expected_checks=["LANG-2", "LANG-3", "LANG-4"],
            ),
            _complex_language,
        ),
        Fault(
            FaultInfo(
                id="remove_example",
                title="Missing worked example",
                category="examples",
                description="Deletes the worked-example section.",
                injected_text="(section removed)",
                expected_checks=["FLOW-1", "EX-1"],
            ),
            _remove_example,
        ),
        Fault(
            FaultInfo(
                id="broken_flow",
                title="Broken teaching order",
                category="flow",
                description="Moves 'How it works' before 'What it is', so ideas are used before they are introduced.",
                injected_text="(sections reordered)",
                expected_checks=["FLOW-1", "FLOW-2"],
            ),
            _broken_flow,
        ),
        Fault(
            FaultInfo(
                id="wrong_hindi_hint",
                title="Wrong Hindi hint",
                category="accuracy",
                description="Replaces the Hindi meaning of 'Retrieval' with 'बिजली' (electricity).",
                injected_text=WRONG_HINDI,
                expected_checks=["ACC-3"],
            ),
            _wrong_hindi,
        ),
        Fault(
            FaultInfo(
                id="wrong_quiz_answer",
                title="Wrong quiz answer key",
                category="flow",
                description="Marks a wrong option as correct in the first quiz question.",
                injected_text="(answer key changed)",
                expected_checks=["FLOW-4"],
            ),
            _wrong_quiz_answer,
        ),
        Fault(
            FaultInfo(
                id="missing_hindi_hints",
                title="Missing Hindi hints",
                category="jargon",
                description="Replaces the Hindi meaning of three glossary entries with English text.",
                injected_text="(Hindi meanings removed)",
                expected_checks=["JAR-4"],
            ),
            _remove_hindi,
        ),
    ]
}


def list_faults() -> list[FaultInfo]:
    return [f.info for f in FAULTS.values()]


def apply_fault(lesson: Lesson, fault_id: str) -> FaultApplied:
    fault = FAULTS.get(fault_id)
    if fault is None:
        raise NotFoundError(f"unknown fault '{fault_id}'; available: {sorted(FAULTS)}")
    return FaultApplied(lesson=fault.apply(lesson), fault=fault.info)
