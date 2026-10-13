"""Pipeline state. Everything is a JSON-safe dict so checkpoints serialise safely."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from lessongen_common.schemas import Usage


def merge_usage(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Reducer: every node returns only the usage it caused; the state keeps the running total."""
    total = Usage.merge(Usage.model_validate(left or {}), Usage.model_validate(right or {}))
    return total.model_dump(mode="json")


def merge_attempts(
    left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Reducer: append new attempts; a re-evaluation of the same attempt replaces it."""
    by_no = {a["attempt_no"]: a for a in left or []}
    for attempt in right or []:
        by_no[attempt["attempt_no"]] = attempt
    return [by_no[k] for k in sorted(by_no)]


class PipelineState(TypedDict, total=False):
    # Request
    run_id: str
    mode: str
    topic: str
    topic_id: str
    topic_title: str
    helper_language: str
    max_retries: int
    fault_id: str | None
    # Working memory of the loop
    memory: dict[str, Any]
    plan: dict[str, Any] | None
    lesson: dict[str, Any] | None
    previous_lesson: dict[str, Any] | None
    evaluation: dict[str, Any] | None
    attempt: int
    pending_kind: str
    pending_notes: list[dict[str, Any]]
    pending_strategy_reason: str
    pending_generation_usage: dict[str, Any]
    eval_retries: int
    route: str
    route_reason: str
    # The rejection log: one AttemptRecord dict per evaluated attempt
    attempts: Annotated[list[dict[str, Any]], merge_attempts]
    usage: Annotated[dict[str, Any], merge_usage]
    # Outcome
    status: str
    status_reason: str | None
    final_attempt_no: int | None
    consolidation: dict[str, Any] | None
