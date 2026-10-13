"""Human-readable exports: the lesson (for the Google Doc) and the rejection log."""

from __future__ import annotations

from lessongen_common.schemas.evaluation import CheckResult, EvaluationReport
from lessongen_common.schemas.lesson import Lesson
from lessongen_common.schemas.rubric import DIMENSION_LABELS
from lessongen_common.schemas.run import AttemptRecord, RunDetail, RunStatus

_STATUS_LABEL = {
    RunStatus.SHIPPED: "SHIPPED",
    RunStatus.NEEDS_HUMAN_REVIEW: "NEEDS HUMAN REVIEW",
    RunStatus.EVALUATED: "EVALUATED",
    RunStatus.FAILED: "FAILED",
    RunStatus.CANCELLED: "CANCELLED",
    RunStatus.RUNNING: "RUNNING",
    RunStatus.QUEUED: "QUEUED",
}


def _cell(text: str, limit: int = 220) -> str:
    flat = " ".join(text.split()).replace("|", "\\|")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def lesson_to_markdown(lesson: Lesson, *, helper_language: str = "Hindi") -> str:
    out: list[str] = [f"# {lesson.title}", ""]
    if lesson.learning_objectives:
        out += ["**By the end of this lesson, you will be able to:**", ""]
        out += [f"- {o}" for o in lesson.learning_objectives]
        out.append("")
    for section in lesson.sections:
        out += [f"## {section.heading}", "", section.body_markdown.strip(), ""]
    if lesson.glossary:
        out += [
            "## Key words (Glossary)",
            "",
            f"| Word | Simple meaning | {helper_language} |",
            "|---|---|---|",
        ]
        out += [
            f"| **{_cell(g.term, 80)}** | {_cell(g.simple_meaning, 300)} | {_cell(g.helper_meaning, 120)} |"
            for g in lesson.glossary
        ]
        out.append("")
    if lesson.quiz:
        out += ["## Check your understanding", ""]
        for i, q in enumerate(lesson.quiz, start=1):
            out.append(f"**{i}. {q.question}**")
            out.append("")
            for j, option in enumerate(q.options):
                out.append(f"- {chr(65 + j)}) {option}")
            out.append("")
        out += ["### Answers", ""]
        for i, q in enumerate(lesson.quiz, start=1):
            letter = chr(65 + q.correct_option_index) if 0 <= q.correct_option_index < 26 else "?"
            out.append(f"{i}. **{letter}** - {q.explanation}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _failure_rows(results: list[CheckResult]) -> list[str]:
    rows = ["| Check | Dimension | Why it failed | Evidence |", "|---|---|---|---|"]
    for r in results:
        evidence = "; ".join(f"“{_cell(e, 120)}”" for e in r.evidence[:2]) or "-"
        rows.append(
            f"| **{r.check_id}** {_cell(r.title, 60)} | {DIMENSION_LABELS.get(r.dimension, r.dimension)} "
            f"| {_cell(r.reasoning)} | {evidence} |"
        )
    return rows


def _attempt_block(
    attempt: AttemptRecord, report: EvaluationReport, total_checks: int
) -> list[str]:
    failed = report.failed_results()
    verdict = "PASSED" if report.passed else "REJECTED"
    out = [
        f"## Attempt {attempt.attempt_no} — {verdict} "
        f"({total_checks - len(failed)}/{total_checks} checks passed) · {attempt.kind.value}",
        "",
    ]
    if attempt.strategy_reason:
        out += [f"_Strategy:_ {attempt.strategy_reason}", ""]
    if attempt.revision_notes:
        out += ["**What changed (writer's revision notes):**", ""]
        out += [f"- `{n.check_id}` → {n.change}" for n in attempt.revision_notes]
        out.append("")
    changed = [d for d in attempt.diff if d.change != "unchanged"]
    if changed:
        out += [
            "**Sections touched:** "
            + ", ".join(
                f"{d.heading} ({d.change}, {d.words_before}→{d.words_after} words)" for d in changed
            ),
            "",
        ]
    if failed:
        out += ["**Failed checks:**", "", *_failure_rows(failed), ""]
        fixes = [f"- `{r.check_id}`: {r.fix_instruction}" for r in failed if r.fix_instruction]
        if fixes:
            out += ["**Fix instructions fed back to the writer:**", "", *fixes, ""]
    else:
        out += ["All checks passed — the lesson cleared the bar.", ""]
    return out


def rejection_log_to_markdown(run: RunDetail) -> str:
    status = _STATUS_LABEL.get(run.status, run.status.value.upper())
    out = [
        f"# Rejection log — {run.topic}",
        "",
        f"- **Run:** `{run.id}` ({run.mode.value})",
        f"- **Outcome:** {status}"
        + (f" on attempt {run.final_attempt_no}" if run.final_attempt_no else "")
        + (f" — {run.status_reason}" if run.status_reason else ""),
        f"- **Attempts:** {run.attempts_count} (max retries: {run.max_retries})",
        f"- **Rubric version:** v{run.rubric_version}"
        if run.rubric_version
        else "- **Rubric version:** -",
        f"- **Guidelines applied from memory:** {len(run.guideline_ids_applied)}",
        f"- **LLM cost:** ${run.usage.cost_usd:.3f} across {run.usage.llm_calls} calls",
        "",
    ]
    for attempt in sorted(run.attempts, key=lambda a: a.attempt_no):
        total = len(attempt.evaluation.results)
        out += _attempt_block(attempt, attempt.evaluation, total)
    return "\n".join(out).rstrip() + "\n"
