"""Applying an approved rubric proposal produces a new, validated rubric version.

Guardrail: this is only ever called from a *human-approved* proposal. The system may
sharpen its own writing guidelines automatically, but it can never change its own
quality bar without a person signing off.
"""

from __future__ import annotations

from typing import Any

from lessongen_common.errors import LessongenError
from lessongen_common.schemas.rubric import Rubric


def apply_clarification(rubric: Rubric, change: dict[str, Any]) -> Rubric:
    check_id = change.get("check_id")
    if not check_id:
        raise LessongenError("proposal change is missing 'check_id'")
    rubric.by_id(check_id)  # raises KeyError for unknown checks
    data = rubric.model_dump(mode="json")
    for check in data["checks"]:
        if check["id"] != check_id:
            continue
        judge = check.get("judge")
        if judge is not None:
            for key, target in (
                ("add_notes", "notes"),
                ("add_pass_criteria", "pass_criteria"),
                ("add_fail_criteria", "fail_criteria"),
            ):
                additions = [str(x).strip() for x in change.get(key, []) if str(x).strip()]
                judge[target] = [*judge.get(target, []), *additions]
        elif any(k in change for k in ("add_notes", "add_pass_criteria", "add_fail_criteria")):
            raise LessongenError(f"{check_id} is not an LLM-judge check; only params can change")
        if isinstance(change.get("params"), dict):
            check["params"] = {**check.get("params", {}), **change["params"]}
    data["version"] = rubric.version + 1
    return Rubric.model_validate(data)
