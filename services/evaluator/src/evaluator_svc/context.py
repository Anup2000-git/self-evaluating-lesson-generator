"""Everything one evaluation needs, computed once and shared by all checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property

from lessongen_common import textmetrics as tm
from lessongen_common.audience import AUDIENCE_SHORT
from lessongen_common.rendering import lesson_to_markdown
from lessongen_common.schemas import CheckSpec, JudgeSpec, Lesson, Rubric, TopicPack

_EVIDENCE_NOISE = re.compile(r"[*_`>#|\[\]]")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def normalize_for_match(text: str) -> str:
    text = _EVIDENCE_NOISE.sub(" ", text.translate(_QUOTES).lower())
    return " ".join(text.split())


class _SafeDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass
class EvalContext:
    lesson: Lesson
    topic: TopicPack
    rubric: Rubric
    helper_language: str
    extras: dict[str, object] = field(default_factory=dict)

    @cached_property
    def body_markdown(self) -> str:
        """What the learner reads as 'the lesson' (sections only, no headings)."""
        return "\n\n".join(s.body_markdown for s in self.lesson.sections)

    @cached_property
    def lesson_markdown(self) -> str:
        """Full rendering judges read (objectives, sections, glossary, quiz with answers)."""
        return lesson_to_markdown(self.lesson, helper_language=self.helper_language)

    @cached_property
    def normalized_lesson(self) -> str:
        return normalize_for_match(self.lesson_markdown)

    @cached_property
    def english_body(self) -> str:
        return tm.english_only(tm.strip_markdown(self.body_markdown))

    @cached_property
    def allowed_terms(self) -> list[str]:
        terms = [g.term for g in self.lesson.glossary]
        for jargon in self.topic.jargon:
            terms += [jargon.term, *jargon.aliases]
        return terms + list(self.topic.allowed_vocabulary)

    def readability(
        self, *, long_sentence_words: int = 28, zipf_threshold: float = tm.DEFAULT_ZIPF_THRESHOLD
    ) -> tm.ReadabilityReport:
        key = f"readability:{long_sentence_words}:{zipf_threshold}"
        if key not in self.extras:
            self.extras[key] = tm.analyze(
                self.body_markdown,
                allowed_words=self.allowed_terms,
                long_sentence_words=long_sentence_words,
                zipf_threshold=zipf_threshold,
            )
        return self.extras[key]  # type: ignore[return-value]

    # ---------------------------------------------------------------- judges
    @cached_property
    def placeholders(self) -> _SafeDict:
        kp = self.topic.key_points
        return _SafeDict(
            topic_title=self.topic.title,
            what=kp.what,
            why_points="; ".join(kp.why),
            how_steps="; ".join(f"({i}) {s}" for i, s in enumerate(kp.how_steps, start=1)),
            misconceptions="; ".join(kp.misconceptions),
            limitations="; ".join(kp.limitations),
            example_must_show="; ".join(self.topic.example_must_show)
            or "every step with concrete content",
            jargon_examples=", ".join(j.term for j in self.topic.jargon[:10]),
            helper_language=self.helper_language,
            audience=AUDIENCE_SHORT,
        )

    def render(self, text: str) -> str:
        return text.format_map(self.placeholders)

    def rendered_judge(self, spec: CheckSpec) -> JudgeSpec:
        assert spec.judge is not None
        j = spec.judge
        return JudgeSpec(
            question=self.render(j.question),
            pass_criteria=[self.render(c) for c in j.pass_criteria],
            fail_criteria=[self.render(c) for c in j.fail_criteria],
            notes=[self.render(n) for n in j.notes],
        )
