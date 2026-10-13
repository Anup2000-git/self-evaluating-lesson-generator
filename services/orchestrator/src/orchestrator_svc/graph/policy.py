"""Loop policy as pure functions - the decisions that make the loop safe, testable and explainable.

* route_after_evaluate: ship, re-evaluate (errors only), revise, or stop and escalate.
* choose_strategy: targeted patch when close, full rewrite when far.
* select_best: when retries run out, pick the attempt a human should review.
* section_diff: what changed between attempts (for the rejection log).
"""

from __future__ import annotations

from typing import Literal

from lessongen_common.schemas import (
    AttemptRecord,
    EvaluationReport,
    Lesson,
    ReviseStrategy,
    RunMode,
    SectionDiff,
)

Route = Literal["finalize", "evaluate", "revise", "select_best"]


def route_after_evaluate(
    *,
    mode: RunMode,
    report: EvaluationReport,
    attempt: int,
    max_retries: int,
    cost_usd: float,
    budget_usd: float,
    eval_retries_used: int,
    eval_retries_allowed: int,
) -> tuple[Route, str]:
    """Returns the next node and a human-readable reason (shown in the UI and logs)."""
    if report.passed:
        return "finalize", "all checks passed"
    only_errors = bool(report.error_check_ids) and set(report.failed_check_ids) <= set(
        report.error_check_ids
    )
    if only_errors and eval_retries_used < eval_retries_allowed:
        return "evaluate", "only evaluation errors failed - re-evaluating the same lesson"
    if mode == RunMode.EVALUATE_ONLY:
        return "finalize", "evaluate-only run"
    retries_used = attempt - 1
    if retries_used >= max_retries:
        return "select_best", f"max retries reached ({max_retries})"
    if cost_usd >= budget_usd:
        return "select_best", f"budget exhausted (${cost_usd:.2f} of ${budget_usd:.2f})"
    return (
        "revise",
        f"{len(report.failed_check_ids)} check(s) failed - retry {retries_used + 1} of {max_retries}",
    )


def choose_strategy(report: EvaluationReport, patch_max_failed: int) -> tuple[ReviseStrategy, str]:
    failed = len(report.failed_check_ids)
    total = len(report.results)
    if failed <= patch_max_failed:
        return ReviseStrategy.PATCH, (
            f"patch: {failed} of {total} checks failed (<= {patch_max_failed}), so only the "
            "failing parts were edited and passing parts were kept"
        )
    return ReviseStrategy.REWRITE, (
        f"rewrite: {failed} of {total} checks failed (> {patch_max_failed}), so the lesson was "
        "rewritten from the plan with all the feedback"
    )


def select_best(attempts: list[AttemptRecord]) -> AttemptRecord:
    """Fewest critical failures, then fewest failures, then the latest attempt."""
    return min(
        attempts,
        key=lambda a: (
            a.evaluation.critical_failures(),
            len(a.evaluation.failed_check_ids),
            -a.attempt_no,
        ),
    )


def _norm(text: str) -> str:
    return " ".join(text.split())


def section_diff(before: Lesson | None, after: Lesson) -> list[SectionDiff]:
    if before is None:
        return []

    def keyed(lesson: Lesson) -> dict[str, tuple[str, str]]:
        seen: dict[str, int] = {}
        out: dict[str, tuple[str, str]] = {}
        for s in lesson.sections:
            seen[s.kind] = seen.get(s.kind, 0) + 1
            key = s.kind.value if seen[s.kind] == 1 else f"{s.kind.value}#{seen[s.kind]}"
            out[key] = (s.heading, s.body_markdown)
        return out

    old, new = keyed(before), keyed(after)
    diffs: list[SectionDiff] = []
    for key in list(new) + [k for k in old if k not in new]:
        heading = (new.get(key) or old[key])[0]
        before_words = len(old[key][1].split()) if key in old else 0
        after_words = len(new[key][1].split()) if key in new else 0
        if key not in old:
            change = "added"
        elif key not in new:
            change = "removed"
        elif _norm(old[key][1]) != _norm(new[key][1]) or old[key][0] != new[key][0]:
            change = "modified"
        else:
            change = "unchanged"
        diffs.append(
            SectionDiff(
                kind=key.split("#")[0],
                heading=heading,
                change=change,
                words_before=before_words,
                words_after=after_words,
            )
        )
    return diffs
