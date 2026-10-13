"""Helpers shared by the planner and the writer."""

from __future__ import annotations

from pathlib import Path

from lessongen_common.prompts import PromptLibrary
from lessongen_common.schemas import Guideline, GuidelineTarget, MemoryContext

PROMPTS = PromptLibrary(Path(__file__).parent / "prompts")


def guidelines_for(memory: MemoryContext, target: GuidelineTarget) -> list[Guideline]:
    """Guidelines meant for this agent (planner or writer), best first."""
    return [g for g in memory.guidelines if g.target in (target, GuidelineTarget.BOTH)]


def focus_lines(memory: MemoryContext, titles: dict[str, str]) -> list[str]:
    return [
        f"{f.check_id} {titles.get(f.check_id, '')}: failed on the first attempt in "
        f"{f.first_attempt_failures} of the last {f.runs} runs"
        for f in memory.frequent_failures
    ]
