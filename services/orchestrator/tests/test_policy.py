"""The loop's decisions are pure functions - tested as a table."""

import pytest

from lessongen_common.schemas import (
    AttemptKind,
    AttemptRecord,
    ReviseStrategy,
    RunMode,
    SectionKind,
)
from lessongen_common.testing import sample_lesson, sample_report
from orchestrator_svc.graph.policy import (
    choose_strategy,
    route_after_evaluate,
    section_diff,
    select_best,
)


def _route(
    failed=(), *, errors=(), mode=RunMode.GENERATE, attempt=1, max_retries=2, cost=0.0, eval_used=0
):
    report = sample_report(failed)
    report.error_check_ids = list(errors)
    return route_after_evaluate(
        mode=mode,
        report=report,
        attempt=attempt,
        max_retries=max_retries,
        cost_usd=cost,
        budget_usd=5.0,
        eval_retries_used=eval_used,
        eval_retries_allowed=1,
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "finalize"),  # all checks passed -> ship
        ({"failed": ["EX-1"]}, "revise"),  # first failure, retries left
        ({"failed": ["EX-1"], "attempt": 2}, "revise"),  # one retry used, one left
        ({"failed": ["EX-1"], "attempt": 3}, "select_best"),  # both retries used -> escalate
        ({"failed": ["EX-1"], "max_retries": 0}, "select_best"),
        ({"failed": ["EX-1"], "cost": 9.9}, "select_best"),  # budget exhausted
        ({"failed": ["FLOW-2"], "errors": ["FLOW-2"]}, "evaluate"),  # only errors -> re-evaluate
        ({"failed": ["FLOW-2"], "errors": ["FLOW-2"], "eval_used": 1}, "revise"),
        ({"failed": ["FLOW-2", "EX-1"], "errors": ["FLOW-2"]}, "revise"),  # a real failure too
        ({"failed": ["EX-1"], "mode": RunMode.EVALUATE_ONLY}, "finalize"),
    ],
)
def test_route_after_evaluate(kwargs: dict, expected: str) -> None:
    route, reason = _route(**kwargs)
    assert route == expected
    assert reason


def test_strategy_patches_when_close_and_rewrites_when_far() -> None:
    assert choose_strategy(sample_report(["EX-1", "JAR-2"]), 6)[0] == ReviseStrategy.PATCH
    many = ["EX-1", "EX-2", "JAR-1", "JAR-2", "COV-1", "COV-2", "FLOW-2"]
    strategy, reason = choose_strategy(sample_report(many), 6)
    assert strategy == ReviseStrategy.REWRITE and "7 of 23" in reason


def test_select_best_prefers_fewest_critical_then_fewest_failures_then_latest() -> None:
    from datetime import UTC, datetime

    def attempt(no: int, failed: list[str]) -> AttemptRecord:
        return AttemptRecord(
            attempt_no=no,
            kind=AttemptKind.PATCH,
            lesson=sample_lesson(),
            evaluation=sample_report(failed),
            created_at=datetime.now(UTC),
        )

    attempts = [attempt(1, ["ACC-1"]), attempt(2, ["EX-1", "EX-2"]), attempt(3, ["EX-1", "LANG-2"])]
    assert select_best(attempts).attempt_no == 3  # no critical failures; tie on count -> latest
    assert select_best(attempts[:2]).attempt_no == 2


def test_section_diff_reports_what_changed() -> None:
    before = sample_lesson()
    after = before.model_copy(deep=True)
    after.sections[3].body_markdown += "\n\nOne more line."
    after.sections = [s for s in after.sections if s.kind != SectionKind.MISCONCEPTIONS]
    changes = {d.kind: d.change for d in section_diff(before, after)}
    assert changes["how"] == "modified"
    assert changes["misconceptions"] == "removed"
    assert changes["what"] == "unchanged"
    assert section_diff(None, after) == []
