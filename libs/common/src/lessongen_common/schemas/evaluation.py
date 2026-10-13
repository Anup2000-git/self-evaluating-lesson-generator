"""Evaluation results: one binary verdict per rubric check, no partial credit."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from lessongen_common.schemas.lesson import Lesson
from lessongen_common.schemas.rubric import CheckMethod, Dimension, Severity
from lessongen_common.schemas.usage import Usage


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class JudgeVote(BaseModel):
    model: str
    verdict: Verdict
    reasoning: str


class CheckResult(BaseModel):
    check_id: str
    dimension: Dimension
    title: str
    method: CheckMethod
    severity: Severity
    verdict: Verdict
    reasoning: str
    evidence: list[str] = Field(default_factory=list)
    fix_instruction: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_verified: bool | None = None
    votes: list[JudgeVote] = Field(
        default_factory=list, description="Judge votes when a FAIL was confirmed or disputed."
    )
    latency_ms: int = 0

    @property
    def passed(self) -> bool:
        return self.verdict == Verdict.PASS


class EvaluateRequest(BaseModel):
    lesson: Lesson
    topic_id: str
    helper_language: str = "Hindi"
    rubric_version: int | None = None


class EvaluationReport(BaseModel):
    rubric_version: int
    passed: bool
    results: list[CheckResult]
    failed_check_ids: list[str]
    summary: str
    usage: Usage = Field(default_factory=Usage)
    duration_ms: int = 0

    @classmethod
    def build(
        cls,
        *,
        rubric_version: int,
        results: list[CheckResult],
        usage: Usage,
        duration_ms: int,
        check_order: list[str],
    ) -> EvaluationReport:
        order = {cid: i for i, cid in enumerate(check_order)}
        ordered = sorted(results, key=lambda r: order.get(r.check_id, len(order)))
        failed = [r.check_id for r in ordered if not r.passed]
        total = len(ordered)
        summary = (
            f"PASS - all {total} checks passed"
            if not failed
            else f"FAIL - {len(failed)} of {total} checks failed: {', '.join(failed)}"
        )
        return cls(
            rubric_version=rubric_version,
            passed=not failed,
            results=ordered,
            failed_check_ids=failed,
            summary=summary,
            usage=usage,
            duration_ms=duration_ms,
        )

    def failed_results(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def critical_failures(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == Severity.CRITICAL)
