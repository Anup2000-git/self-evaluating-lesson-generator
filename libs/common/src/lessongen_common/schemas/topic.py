"""Topic packs: the curated, versioned ground truth a lesson is grounded in."""

from __future__ import annotations

from pydantic import BaseModel, Field

from lessongen_common.schemas.lesson import REQUIRED_SECTIONS, SectionKind


class KeyPoints(BaseModel):
    what: str = Field(description="The one-sentence definition every lesson must convey.")
    why: list[str] = Field(description="Problems the topic solves; lessons must explain >= 2.")
    how_steps: list[str] = Field(description="Ordered steps of how it works.")
    misconceptions: list[str]
    limitations: list[str]


class JargonTerm(BaseModel):
    term: str
    aliases: list[str] = Field(default_factory=list)


class LearnerQuestion(BaseModel):
    id: str
    question: str
    reference_answer: str


class TopicPackSummary(BaseModel):
    id: str
    title: str
    aliases: list[str]
    summary: str
    version: str
    document_count: int
    chunk_count: int


class TopicPack(BaseModel):
    id: str
    title: str
    version: str
    aliases: list[str]
    summary: str
    key_points: KeyPoints
    example_must_show: list[str] = Field(
        default_factory=list,
        description="Parts a worked example must show (used by rubric check EX-1).",
    )
    jargon: list[JargonTerm]
    acronyms: dict[str, str]
    allowed_vocabulary: list[str] = Field(
        default_factory=list,
        description="Words never counted as 'difficult' (e.g. everyday tech words learners know).",
    )
    required_sections: list[SectionKind] = Field(default_factory=lambda: list(REQUIRED_SECTIONS))
    # Held-out assessment items. Never shown to the writer, so it cannot teach to the test.
    learner_questions: list[LearnerQuestion] = Field(default_factory=list)


class GlossaryItem(BaseModel):
    term: str
    aliases: list[str] = Field(default_factory=list)
    simple_meaning: str
    translations: dict[str, str] = Field(
        default_factory=dict, description="Helper-language meanings keyed by lowercase language."
    )


class KBChunk(BaseModel):
    id: str
    doc_id: str
    doc_title: str
    heading: str
    text: str
    source: str


class SearchHit(BaseModel):
    chunk: KBChunk
    score: float


class SearchRequest(BaseModel):
    topic_id: str
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=4, ge=1, le=10)


class SearchResponse(BaseModel):
    topic_id: str
    query: str
    retriever: str
    hits: list[SearchHit]


class TopicResolveRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class TopicResolution(BaseModel):
    topic_id: str
    title: str
    confidence: float


class GlossaryLookupRequest(BaseModel):
    terms: list[str] = Field(min_length=1, max_length=25)


class GlossaryLookupResponse(BaseModel):
    found: list[GlossaryItem]
    missing: list[str]


class KBDocument(BaseModel):
    id: str
    title: str
    source: str
    chunks: list[KBChunk]
