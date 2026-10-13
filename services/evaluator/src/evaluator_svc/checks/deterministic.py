"""Deterministic rubric checks: pure code, no LLM, fully reproducible.

Each implementation is registered under the ``impl`` name the rubric refers to, receives
the shared ``EvalContext`` and the check spec (for its ``params``) and returns a binary
``CheckResult`` with evidence and a concrete fix instruction.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from evaluator_svc.context import EvalContext
from lessongen_common import textmetrics as tm
from lessongen_common.schemas import (
    TEACHING_ORDER,
    CheckResult,
    CheckSpec,
    Verdict,
)

CheckImpl = Callable[[EvalContext, CheckSpec], CheckResult]
REGISTRY: dict[str, CheckImpl] = {}


def register(name: str) -> Callable[[CheckImpl], CheckImpl]:
    def decorator(fn: CheckImpl) -> CheckImpl:
        REGISTRY[name] = fn
        return fn

    return decorator


def result(
    spec: CheckSpec,
    passed: bool,
    reasoning: str,
    *,
    evidence: list[str] | None = None,
    fix: str = "",
    details: dict[str, object] | None = None,
) -> CheckResult:
    return CheckResult(
        check_id=spec.id,
        dimension=spec.dimension,
        title=spec.title,
        method=spec.method,
        severity=spec.severity,
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        reasoning=reasoning,
        evidence=(evidence or [])[:5],
        fix_instruction="" if passed else fix,
        details=details or {},
    )


def _stem_key(text: str) -> tuple[str, ...]:
    return tuple(tm.stem(w) for part in tm.words(text) for w in part.split("-") if w)


# ------------------------------------------------------------------ language
@register("readability_grade")
def readability_grade(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    limit = float(spec.params.get("max_grade", 8.0))
    report = ctx.readability()
    passed = report.fk_grade <= limit
    hardest = sorted(
        tm.split_sentences(ctx.english_body),
        key=lambda s: (
            sum(tm.syllables(w) for w in tm.words(s)) / max(1, len(tm.words(s))) * len(tm.words(s))
        ),
        reverse=True,
    )[:2]
    return result(
        spec,
        passed,
        f"Flesch-Kincaid grade is {report.fk_grade} (limit {limit}); average sentence "
        f"{report.avg_sentence_words} words.",
        evidence=[] if passed else hardest,
        fix="Lower the reading level: split long sentences, and replace long words with short "
        "everyday words. Start with the hardest sentences quoted in the evidence.",
        details={"fk_grade": report.fk_grade, "limit": limit},
    )


@register("sentence_length")
def sentence_length(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    max_avg = float(spec.params.get("max_avg_words", 15))
    max_words = int(spec.params.get("max_words", 28))
    report = ctx.readability(long_sentence_words=max_words)
    passed = report.avg_sentence_words <= max_avg and not report.long_sentences
    problems = []
    if report.avg_sentence_words > max_avg:
        problems.append(f"average sentence is {report.avg_sentence_words} words (limit {max_avg})")
    if report.long_sentences:
        problems.append(f"{len(report.long_sentences)} sentence(s) longer than {max_words} words")
    return result(
        spec,
        passed,
        "Sentence lengths are within limits."
        if passed
        else "Sentences are too long: " + "; ".join(problems) + ".",
        evidence=report.long_sentences,
        fix=f"Split every sentence longer than {max_words} words into two or three short sentences "
        "(one idea per sentence).",
        details={
            "avg_sentence_words": report.avg_sentence_words,
            "max_sentence_words": report.max_sentence_words,
            "long_sentences": len(report.long_sentences),
        },
    )


@register("difficult_vocabulary")
def difficult_vocabulary(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    max_distinct = int(spec.params.get("max_distinct", 10))
    threshold = float(spec.params.get("zipf_threshold", tm.DEFAULT_ZIPF_THRESHOLD))
    hard = ctx.readability(zipf_threshold=threshold).difficult_words
    passed = len(hard) <= max_distinct
    return result(
        spec,
        passed,
        f"{len(hard)} distinct difficult word(s) outside the glossary and jargon list "
        f"(limit {max_distinct})" + (f": {', '.join(hard[:15])}." if hard else "."),
        evidence=[", ".join(hard[:25])] if hard else [],
        fix="Replace these rare words with common everyday words, or explain them and add them "
        "to the glossary: " + ", ".join(hard[:25]),
        details={"difficult_words": hard, "limit": max_distinct},
    )


@register("lesson_length")
def lesson_length(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    low = int(spec.params.get("min_words", 900))
    high = int(spec.params.get("max_words", 2000))
    count = ctx.readability().word_count
    passed = low <= count <= high
    direction = "too short" if count < low else "too long"
    return result(
        spec,
        passed,
        f"The lesson body has {count} words (allowed {low}-{high}).",
        fix=(
            f"The lesson is {direction}. "
            + (
                f"Add about {low - count} words of explanation and examples."
                if count < low
                else f"Cut about {count - high} words: remove repetition and side topics."
            )
        ),
        details={"word_count": count},
    )


# -------------------------------------------------------------------- jargon
def _glossary_keys(ctx: EvalContext) -> set[tuple[str, ...]]:
    keys: set[tuple[str, ...]] = set()
    for entry in ctx.lesson.glossary:
        inside = re.findall(r"\(([^)]*)\)", entry.term)
        outside = re.sub(r"\([^)]*\)", " ", entry.term)
        for variant in [outside, *inside, *re.split(r"\s*/\s*", outside)]:
            key = _stem_key(variant)
            if key:
                keys.add(key)
    return keys


@register("glossary_covers_jargon")
def glossary_covers_jargon(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    tokens = [tm.stem(w) for token in tm.words(ctx.english_body) for w in token.split("-") if w]
    variants = sorted(
        ((j.term, _stem_key(name)) for j in ctx.topic.jargon for name in [j.term, *j.aliases]),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    covered_by: dict[str, set[tuple[str, ...]]] = {}
    for j in ctx.topic.jargon:
        covered_by[j.term] = {_stem_key(n) for n in [j.term, *j.aliases]}
    mask = [False] * len(tokens)
    used: set[str] = set()
    for term, key in variants:
        n = len(key)
        if not n:
            continue
        for i in range(len(tokens) - n + 1):
            if tuple(tokens[i : i + n]) == key and not any(mask[i : i + n]):
                mask[i : i + n] = [True] * n
                used.add(term)
    glossary = _glossary_keys(ctx)
    missing = sorted(t for t in used if not (covered_by[t] & glossary))
    return result(
        spec,
        not missing,
        f"{len(used)} technical term(s) used; all have glossary entries."
        if not missing
        else f"Technical terms used without a glossary entry: {', '.join(missing)}.",
        evidence=missing,
        fix="Add a glossary entry (term, one-sentence simple meaning, helper-language meaning) "
        "for: " + ", ".join(missing),
        details={"terms_used": sorted(used), "missing": missing},
    )


def _expanded_nearby(window: str, expansion: str) -> bool:
    needed = {tm.stem(w) for w in tm.words(expansion) if len(w) > 2}
    present = {tm.stem(w) for w in tm.words(window)}
    return bool(needed) and needed <= present


@register("acronyms_expanded")
def acronyms_expanded(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    text = tm.english_only(
        tm.strip_markdown("\n".join(ctx.lesson.learning_objectives) + "\n" + ctx.body_markdown)
    )
    familiar = {a.upper() for a in ctx.topic.familiar_acronyms}
    known = {k.upper(): v for k, v in ctx.topic.acronyms.items()}
    seen: set[str] = set()
    unexpanded: list[str] = []
    evidence: list[str] = []
    for match in re.finditer(r"\b([A-Z][A-Z0-9]{1,})(s?)\b", text):
        acronym = match.group(1)
        if acronym in seen or acronym in familiar or not any(c.isalpha() for c in acronym):
            continue
        if acronym not in known and tm.word_frequency(acronym.lower()) >= 4.5:
            continue  # an ordinary word in capitals for emphasis ("NOT"), not an acronym
        seen.add(acronym)
        start, end = match.span()
        window = text[max(0, start - 160) : end + 160]
        if acronym in known:
            ok = _expanded_nearby(window, known[acronym])
        else:
            after = text[end : end + 4]
            before = text[max(0, start - 2) : start]
            ok = "(" in after or before.endswith("(")
        if not ok:
            unexpanded.append(acronym)
            sentence = next((s for s in tm.split_sentences(window) if acronym in s), window.strip())
            evidence.append(sentence[:220])
    return result(
        spec,
        not unexpanded,
        "Every acronym is written out in full at its first use."
        if not unexpanded
        else f"Acronyms used without being written out in full at first use: {', '.join(unexpanded)}.",
        evidence=evidence,
        fix="At the first use of each of these acronyms, write the full form next to it, e.g. "
        "'LLM (Large Language Model)': " + ", ".join(unexpanded),
        details={"acronyms": sorted(seen), "unexpanded": unexpanded},
    )


@register("helper_hints_present")
def helper_hints_present(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    language = ctx.helper_language
    missing = []
    for entry in ctx.lesson.glossary:
        hint = entry.helper_meaning.strip()
        script_ok = tm.has_script(hint, language)
        if not hint or script_ok is False:
            missing.append(entry.term)
    return result(
        spec,
        not missing and bool(ctx.lesson.glossary),
        f"All {len(ctx.lesson.glossary)} glossary entries have a {language} meaning."
        if not missing
        else f"Glossary entries without a {language} meaning in {language} script: {', '.join(missing)}.",
        evidence=missing,
        fix=f"Give every glossary entry a short, correct {language} meaning written in {language} "
        "script: " + ", ".join(missing),
        details={"missing": missing, "language": language},
    )


# ---------------------------------------------------------------------- flow
@register("section_order")
def section_order(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    kinds = [s.kind for s in ctx.lesson.sections]
    required = list(ctx.topic.required_sections)
    missing = [k.value for k in required if k not in kinds]
    first = {k: kinds.index(k) for k in TEACHING_ORDER if k in kinds}
    actual = sorted(first, key=first.__getitem__)
    expected = [k for k in TEACHING_ORDER if k in first]
    in_order = actual == expected
    problems = []
    if missing:
        problems.append(f"missing section(s): {', '.join(missing)}")
    if not in_order:
        problems.append(
            "sections are out of teaching order: found "
            + " -> ".join(k.value for k in actual)
            + "; expected "
            + " -> ".join(k.value for k in expected)
        )
    return result(
        spec,
        not problems,
        "All required sections are present in teaching order: "
        + " -> ".join(k.value for k in actual)
        + "."
        if not problems
        else "; ".join(problems).capitalize() + ".",
        evidence=[f"{s.kind.value}: {s.heading}" for s in ctx.lesson.sections],
        fix="Organise the lesson as: what it is -> why it matters -> how it works -> worked "
        "example -> (common mistakes) -> summary, adding any missing section.",
        details={"sections": [k.value for k in kinds], "missing": missing},
    )


@register("quiz_structure")
def quiz_structure(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    p = spec.params
    min_q, max_q = int(p.get("min_questions", 3)), int(p.get("max_questions", 5))
    min_o, max_o = int(p.get("min_options", 3)), int(p.get("max_options", 4))
    quiz = ctx.lesson.quiz
    problems = []
    if not min_q <= len(quiz) <= max_q:
        problems.append(f"has {len(quiz)} questions (need {min_q}-{max_q})")
    for i, q in enumerate(quiz, start=1):
        if not min_o <= len(q.options) <= max_o:
            problems.append(f"Q{i} has {len(q.options)} options (need {min_o}-{max_o})")
        if len({o.strip().lower() for o in q.options}) != len(q.options):
            problems.append(f"Q{i} has duplicate options")
        if not 0 <= q.correct_option_index < len(q.options):
            problems.append(f"Q{i} marks a correct option that does not exist")
        if not q.explanation.strip():
            problems.append(f"Q{i} has no explanation")
    return result(
        spec,
        not problems,
        f"Quiz has {len(quiz)} well-formed multiple-choice questions."
        if not problems
        else "Quiz problems: " + "; ".join(problems) + ".",
        evidence=problems,
        fix=f"Write {min_q}-{max_q} multiple-choice questions, each with {min_o}-{max_o} different "
        "options, exactly one correct option and a short explanation.",
        details={"questions": len(quiz)},
    )


def run_deterministic(ctx: EvalContext, spec: CheckSpec) -> CheckResult:
    if spec.impl not in REGISTRY:
        raise KeyError(f"no deterministic implementation named '{spec.impl}'")
    return REGISTRY[spec.impl](ctx, spec)
