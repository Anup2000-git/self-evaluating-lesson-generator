"""The rubric is data: a versioned list of hard pass/fail checks.

Each check declares *how* it is evaluated (``method``). Deterministic checks reference a
registered implementation by name (``impl``) plus ``params``; LLM-judge checks are fully
described by their ``judge`` spec, so the rubric can be sharpened (new criteria, notes,
thresholds) without code changes - and every report is stamped with the rubric version.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Dimension(StrEnum):
    ACCURACY = "accuracy"
    LANGUAGE = "language"
    EXAMPLES = "examples"
    JARGON = "jargon"
    COVERAGE = "coverage"
    FLOW = "flow"


DIMENSION_LABELS: dict[Dimension, str] = {
    Dimension.ACCURACY: "Accurate & grounded",
    Dimension.LANGUAGE: "Beginner-friendly language",
    Dimension.EXAMPLES: "Teaches by example",
    Dimension.JARGON: "Clear, no unexplained jargon",
    Dimension.COVERAGE: "Covers the key points",
    Dimension.FLOW: "Coherent teaching flow",
}


class CheckMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_JUDGE = "llm_judge"
    FACT_CHECK = "fact_check"
    LEARNER = "learner"


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"


class JudgeSpec(BaseModel):
    question: str = Field(description="The single yes/no question the judge answers.")
    pass_criteria: list[str]
    fail_criteria: list[str]
    notes: list[str] = Field(
        default_factory=list, description="Clarifications added when the rubric is sharpened."
    )


class CheckSpec(BaseModel):
    id: str
    dimension: Dimension
    title: str
    method: CheckMethod
    severity: Severity
    pass_condition: str = Field(description="Human-readable PASS rule shown in the UI and docs.")
    impl: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    judge: JudgeSpec | None = None

    @model_validator(mode="after")
    def _method_requirements(self) -> CheckSpec:
        if self.method == CheckMethod.DETERMINISTIC and not self.impl:
            raise ValueError(f"{self.id}: deterministic checks need 'impl'")
        if self.method == CheckMethod.LLM_JUDGE and self.judge is None:
            raise ValueError(f"{self.id}: llm_judge checks need a 'judge' spec")
        return self


class Rubric(BaseModel):
    version: int
    name: str
    ship_policy: Literal["all_must_pass"] = "all_must_pass"
    description: str = ""
    checks: list[CheckSpec]

    @model_validator(mode="after")
    def _unique_ids(self) -> Rubric:
        ids = [c.id for c in self.checks]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate check ids: {sorted(dupes)}")
        return self

    def by_id(self, check_id: str) -> CheckSpec:
        for check in self.checks:
            if check.id == check_id:
                return check
        raise KeyError(check_id)

    def of_method(self, method: CheckMethod) -> list[CheckSpec]:
        return [c for c in self.checks if c.method == method]
