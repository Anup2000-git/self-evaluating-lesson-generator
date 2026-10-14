"""Verifies that a judge's quoted evidence really appears in the lesson.

LLM judges sometimes "quote" text that is not there. A FAIL backed by a fabricated quote
would send the writer chasing a problem that does not exist, so unverifiable evidence
triggers a re-judgment.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from evaluator_svc.context import normalize_for_match

# Helper-language hints in brackets, e.g. "query (सवाल या खोज)". Quoting models often leave
# them out, so the lesson is also searched without them.
_SCRIPT_HINT = re.compile(r"\s*\([^()]*[ऀ-෿][^()]*\)")
# A quote may join several sentences (or lines) from different places in the lesson.
_FRAGMENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _matches(needle: str, haystacks: tuple[str, ...], threshold: int) -> bool:
    return any(needle in hay or fuzz.partial_ratio(needle, hay) >= threshold for hay in haystacks)


def quote_found(quote: str, normalized_haystack: str, threshold: int) -> bool:
    """True if the quote is in the lesson - as a whole, or every sentence of it verbatim."""
    without_hints = " ".join(_SCRIPT_HINT.sub("", normalized_haystack).split())
    haystacks = (normalized_haystack, without_hints)
    needle = normalize_for_match(quote).strip(" .,:;!?\"'")
    if len(needle) < 4:
        return True  # too short to be meaningful either way
    if _matches(needle, haystacks, threshold):
        return True
    fragments = [
        f
        for f in (
            normalize_for_match(part).strip(" .,:;!?\"'") for part in _FRAGMENT_SPLIT.split(quote)
        )
        if len(f) >= 4
    ]
    return len(fragments) > 1 and all(_matches(f, haystacks, threshold) for f in fragments)


def unverified_quotes(quotes: list[str], normalized_haystack: str, threshold: int) -> list[str]:
    return [q for q in quotes if not quote_found(q, normalized_haystack, threshold)]
