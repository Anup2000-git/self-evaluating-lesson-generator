"""Deterministic text metrics for beginner-friendliness.

Used in two places on purpose:
* the evaluator's deterministic rubric checks (LANG-1/2/3/5), and
* the writer agent's ``check_readability`` tool,
so the writer can self-check with *exactly* the yardstick it will be judged by.

Metrics are computed on English text only: helper-language hints such as
"retrieval (खोज कर लाना)" are stripped first so Devanagari does not distort counts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache

import snowballstemmer
import textstat
from wordfreq import zipf_frequency

# Vocabulary difficulty is measured by how common a word is in English (Zipf frequency:
# 6 = "the", 4 = "deadline", 3 = "seamless"). Learners with limited vocabulary know the
# most frequent words, so a word rarer than DEFAULT_ZIPF_THRESHOLD counts as difficult.
DEFAULT_ZIPF_THRESHOLD = 3.8

# Frequent-but-academic words that LLMs love and beginners struggle with. Always difficult.
ACADEMIC_WORDS: frozenset[str] = frozenset(
    """
    additionally aforementioned comprehensive consequently crucial delve elucidate encompass
    endeavor endeavour enhance facilitate furthermore henceforth holistic leverage moreover
    myriad nevertheless notwithstanding nuanced optimal paradigm paramount pivotal plethora
    robust seamless sophisticated streamline subsequently substantial thereby utilize utilise
    whereas wherein
    """.split()
)

# Words an Indian 12th-grade graduate uses daily even in Hindi-medium schools (many are
# loanwords in Hindi itself) even where they are rarer in global English text.
INDIA_FAMILIAR_WORDS: frozenset[str] = frozenset(
    """
    computer computers internet mobile phone smartphone laptop website app apps online
    information example examples exam exams examination student students teacher teachers
    college school class classes syllabus textbook notebook library question questions
    answer answers problem problems simple important company office business bank
    cricket match score railway station ticket train bus hospital doctor medicine
    government notice result results marks subject subjects science history english
    hindi india indian village city market shop shopkeeper price prices list number
    numbers digital video message messages email chat chatbot chatbots google whatsapp
    youtube camera photo photos minute minutes second seconds today yesterday tomorrow
    kirana semester rupee rupees paisa
    """.split()
)

_STEMMER = snowballstemmer.stemmer("english")

_INDIC_AND_OTHER_SCRIPTS = (
    "؀-ۿ"  # Arabic (Urdu)
    "ऀ-ॿ"  # Devanagari (Hindi, Marathi)
    "ঀ-৿"  # Bengali
    "਀-੿"  # Gurmukhi
    "઀-૿"  # Gujarati
    "଀-୿"  # Odia
    "஀-௿"  # Tamil
    "ఀ-౿"  # Telugu
    "ಀ-೿"  # Kannada
    "ഀ-ൿ"  # Malayalam
)
_NON_LATIN_CHAR = re.compile(f"[{_INDIC_AND_OTHER_SCRIPTS}]")
# "(खोज कर लाना)", "[खोज = search]" or "(Hindi: खोज कर लाना)" -> removed entirely.
_NON_LATIN_GROUP = re.compile(
    r"\s*[\(\[][^\(\)\[\]]*?" + f"[{_INDIC_AND_OTHER_SCRIPTS}]" + r"[^\(\)\[\]]*?[\)\]]"
)
_NON_LATIN_RUN = re.compile(f"[{_INDIC_AND_OTHER_SCRIPTS}][{_INDIC_AND_OTHER_SCRIPTS}\\s,।]*")

SCRIPT_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "hindi": ((0x0900, 0x097F),),
    "marathi": ((0x0900, 0x097F),),
    "nepali": ((0x0900, 0x097F),),
    "sanskrit": ((0x0900, 0x097F),),
    "bengali": ((0x0980, 0x09FF),),
    "assamese": ((0x0980, 0x09FF),),
    "punjabi": ((0x0A00, 0x0A7F),),
    "gujarati": ((0x0A80, 0x0AFF),),
    "odia": ((0x0B00, 0x0B7F),),
    "tamil": ((0x0B80, 0x0BFF),),
    "telugu": ((0x0C00, 0x0C7F),),
    "kannada": ((0x0C80, 0x0CFF),),
    "malayalam": ((0x0D00, 0x0D7F),),
    "urdu": ((0x0600, 0x06FF), (0x0750, 0x077F)),
}

_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "etc.",
    "vs.",
    "Dr.",
    "Mr.",
    "Mrs.",
    "Ms.",
    "No.",
    "approx.",
    "Rs.",
    "St.",
)
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9])")
_WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
_ACRONYM = re.compile(r"\b[A-Z]{2,}s?\b")
_ACRONYM_PLURAL = re.compile(r"[A-Z]{2,}s")


def strip_markdown(markdown: str) -> str:
    """Markdown -> plain text, one logical unit (paragraph, list item, heading) per line."""
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r"[-|:\s*_=]+", line):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^([-*+]|\d+[.)])\s+", "", line)
        line = line.replace("|", " ")
        line = re.sub(r"(\*\*|__|\*|_)(\S.*?\S|\S)\1", r"\2", line)
        line = re.sub(r"\s{2,}", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def english_only(text: str) -> str:
    """Remove helper-language hints (bracketed groups or runs in Indic/Arabic scripts)."""
    text = _NON_LATIN_GROUP.sub("", text)
    text = _NON_LATIN_RUN.sub(" ", text)
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def has_script(text: str, language: str) -> bool | None:
    """True if ``text`` contains characters of the language's script (None = unknown language)."""
    ranges = SCRIPT_RANGES.get(language.strip().lower())
    if ranges is None:
        return None
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in ranges)


def contains_non_latin(text: str) -> bool:
    return bool(_NON_LATIN_CHAR.search(text))


def split_sentences(text: str) -> list[str]:
    """Sentences of plain text; every line (heading, list item) is at least its own unit."""
    protected = text
    for i, abbr in enumerate(_ABBREVIATIONS):
        protected = protected.replace(abbr, f"\x00{i}\x00")
    sentences: list[str] = []
    for line in protected.splitlines():
        for part in _SENTENCE_END.split(line):
            restored = part
            for i, abbr in enumerate(_ABBREVIATIONS):
                restored = restored.replace(f"\x00{i}\x00", abbr)
            restored = restored.strip()
            if _WORD.search(restored):
                sentences.append(restored)
    return sentences


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def acronyms(text: str) -> list[str]:
    return _ACRONYM.findall(text)


def _inflection_candidates(word: str) -> list[str]:
    w = word.lower()
    out = [w]
    if w.endswith("ies") and len(w) > 4:
        out.append(w[:-3] + "y")
    if w.endswith("es") and len(w) > 3:
        out.append(w[:-2])
    if w.endswith("s") and len(w) > 3:
        out.append(w[:-1])
    if w.endswith("ed") and len(w) > 4:
        out += [w[:-2], w[:-1]]
    if w.endswith("ing") and len(w) > 5:
        out += [w[:-3], w[:-3] + "e"]
    if w.endswith("ly") and len(w) > 4:
        out.append(w[:-2])
    if w.endswith("er") and len(w) > 4:
        out += [w[:-2], w[:-1]]
    return out


@lru_cache(maxsize=20000)
def stem(word: str) -> str:
    return _STEMMER.stemWord(word.lower())


def term_stems(term: str) -> set[str]:
    """Stems of every word in a term ('Retrieval' also allows 'retrieve', 'retrieves')."""
    return {stem(w) for part in words(term) for w in part.split("-") if w}


@lru_cache(maxsize=20000)
def word_frequency(word: str) -> float:
    """Zipf frequency of the most common inflection candidate of ``word``."""
    return max(zipf_frequency(c, "en") for c in _inflection_candidates(word))


_FAMILIAR_STEMS = frozenset(stem(w) for w in INDIA_FAMILIAR_WORDS)


def is_difficult(
    word: str,
    allowed_stems: set[str] | frozenset[str] = frozenset(),
    zipf_threshold: float = DEFAULT_ZIPF_THRESHOLD,
) -> bool:
    w = word.lower().replace("’", "'")
    if w.endswith("'s"):
        w = w[:-2]
    w = w.strip("'")
    if not w or len(w) <= 2:
        return False
    s = stem(w)
    if s in allowed_stems or s in _FAMILIAR_STEMS:
        return False
    if w in ACADEMIC_WORDS:
        return True
    return word_frequency(w) < zipf_threshold


def syllables(word: str) -> int:
    return max(1, int(textstat.syllable_count(word)))


@dataclass
class ReadabilityReport:
    word_count: int
    sentence_count: int
    avg_sentence_words: float
    max_sentence_words: int
    fk_grade: float
    long_sentences: list[str] = field(default_factory=list)
    difficult_words: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "word_count": self.word_count,
            "sentence_count": self.sentence_count,
            "avg_sentence_words": self.avg_sentence_words,
            "max_sentence_words": self.max_sentence_words,
            "fk_grade": self.fk_grade,
            "long_sentences": self.long_sentences,
            "difficult_words": self.difficult_words,
        }


def proper_nouns(sentences: list[list[str]]) -> set[str]:
    """Words written Capitalised in the middle of a sentence (names like Riya, Patna, ChatGPT)."""
    found: set[str] = set()
    for ws in sentences:
        for w in ws[1:]:
            if w[0].isupper() and not w.isupper():
                found.add(w.lower())
    return found


def difficult_words(
    sentence_words: list[list[str]],
    *,
    allowed_terms: Iterable[str] = (),
    zipf_threshold: float = DEFAULT_ZIPF_THRESHOLD,
) -> list[str]:
    allowed: set[str] = set()
    for term in allowed_terms:
        allowed |= term_stems(term)
    names = proper_nouns(sentence_words)
    found: set[str] = set()
    for ws in sentence_words:
        for token in ws:
            for part in token.split("-"):
                if not part or part.isupper() or _ACRONYM_PLURAL.fullmatch(part):
                    continue
                if part.lower() in names:
                    continue
                if is_difficult(part, allowed, zipf_threshold):
                    found.add(part.lower().removesuffix("'s").removesuffix("’s"))
    return sorted(found)


def analyze(
    markdown: str,
    *,
    allowed_words: Iterable[str] = (),
    long_sentence_words: int = 28,
    zipf_threshold: float = DEFAULT_ZIPF_THRESHOLD,
) -> ReadabilityReport:
    """Readability of Markdown text, ignoring helper-language hints.

    Flesch-Kincaid grade is computed with our own sentence splitter (textstat's splitter
    counts a whole bullet list as one sentence, which inflates the grade).
    """
    text = english_only(strip_markdown(markdown))
    sentences = split_sentences(text)
    sentence_words = [words(s) for s in sentences]
    all_words = [w for ws in sentence_words for w in ws]
    n_words = len(all_words)
    n_sentences = max(1, len(sentences))
    if n_words == 0:
        return ReadabilityReport(0, 0, 0.0, 0, 0.0)

    syllable_total = sum(syllables(w) for w in all_words)
    fk = 0.39 * (n_words / n_sentences) + 11.8 * (syllable_total / n_words) - 15.59

    difficult = difficult_words(
        sentence_words, allowed_terms=allowed_words, zipf_threshold=zipf_threshold
    )
    long_ones = [
        s for s, ws in zip(sentences, sentence_words, strict=True) if len(ws) > long_sentence_words
    ]
    return ReadabilityReport(
        word_count=n_words,
        sentence_count=len(sentences),
        avg_sentence_words=round(n_words / n_sentences, 2),
        max_sentence_words=max(len(ws) for ws in sentence_words),
        fk_grade=round(fk, 2),
        long_sentences=long_ones,
        difficult_words=difficult,
    )
