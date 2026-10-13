"""Verifies that a judge's quoted evidence really appears in the lesson.

LLM judges sometimes "quote" text that is not there. A FAIL backed by a fabricated quote
would send the writer chasing a problem that does not exist, so unverifiable evidence
triggers a re-judgment.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from evaluator_svc.context import normalize_for_match


def quote_found(quote: str, normalized_haystack: str, threshold: int) -> bool:
    needle = normalize_for_match(quote).strip(" .,:;!?\"'")
    if len(needle) < 4:
        return True  # too short to be meaningful either way
    if needle in normalized_haystack:
        return True
    return fuzz.partial_ratio(needle, normalized_haystack) >= threshold


def unverified_quotes(quotes: list[str], normalized_haystack: str, threshold: int) -> list[str]:
    return [q for q in quotes if not quote_found(q, normalized_haystack, threshold)]
