from pathlib import Path

import pytest
import yaml

from generator_svc.settings import GeneratorSettings
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import (
    GenerationContext,
    GlossaryItem,
    GlossaryLookupResponse,
    Guideline,
    GuidelineOrigin,
    GuidelineStatus,
    GuidelineTarget,
    KBChunk,
    MemoryContext,
    SearchHit,
    SearchResponse,
    TopicPack,
)

PACK_DIR = (
    Path(__file__).resolve().parents[2] / "knowledge" / "src" / "knowledge_svc" / "packs" / "rag"
)


class FakeKnowledge:
    def __init__(self) -> None:
        self.pack = TopicPack.model_validate(
            yaml.safe_load((PACK_DIR / "pack.yaml").read_text(encoding="utf-8"))
        )
        self.items = [
            GlossaryItem.model_validate(g)
            for g in yaml.safe_load((PACK_DIR / "glossary.yaml").read_text(encoding="utf-8"))
        ]
        self.queries: list[str] = []

    async def topic(self, topic_id: str, *, include_assessment: bool = False) -> TopicPack:
        assert not include_assessment, "the generator must never see the held-out questions"
        return self.pack.model_copy(update={"learner_questions": []})

    async def search(self, topic_id: str, query: str, k: int = 4) -> SearchResponse:
        self.queries.append(query)
        chunk = KBChunk(
            id=f"rag/doc#{len(self.queries)}",
            doc_id="rag/doc",
            doc_title="Doc",
            heading="Heading",
            text=f"Fact about {query}.",
            source="curated",
        )
        return SearchResponse(
            topic_id=topic_id,
            query=query,
            retriever="bm25",
            hits=[SearchHit(chunk=chunk, score=1.0)],
        )

    async def glossary(self, topic_id: str) -> list[GlossaryItem]:
        return self.items

    async def lookup(self, topic_id: str, terms: list[str]) -> GlossaryLookupResponse:
        found = [
            i
            for i in self.items
            if any(t.lower() in (i.term.lower(), *[a.lower() for a in i.aliases]) for t in terms)
        ]
        names = {n.lower() for i in found for n in (i.term, *i.aliases)}
        return GlossaryLookupResponse(
            found=found, missing=[t for t in terms if t.lower() not in names]
        )


class FakeRubrics:
    async def get(self, version: int | None = None):
        return load_seed_rubric()


@pytest.fixture
def knowledge() -> FakeKnowledge:
    return FakeKnowledge()


@pytest.fixture
def rubrics() -> FakeRubrics:
    return FakeRubrics()


@pytest.fixture
def settings() -> GeneratorSettings:
    return GeneratorSettings(_env_file=None, events_enabled=False, log_json=False)  # type: ignore[call-arg]


@pytest.fixture
def context() -> GenerationContext:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    guideline = Guideline(
        id="G-1",
        topic_id="rag",
        text="Explain 'embedding' as a list of numbers before using it.",
        check_ids=["JAR-2"],
        target=GuidelineTarget.WRITER,
        status=GuidelineStatus.ACTIVE,
        origin=GuidelineOrigin.FAILURE,
        version=1,
        times_applied=2,
        times_helped=2,
        times_missed=0,
        created_from_run="r0",
        created_at=now,
        updated_at=now,
    )
    planner_only = guideline.model_copy(
        update={"id": "G-2", "text": "Plan the analogy first.", "target": GuidelineTarget.PLANNER}
    )
    return GenerationContext(
        topic_id="rag",
        topic_title="Introduction to RAG",
        helper_language="Hindi",
        memory=MemoryContext(
            topic_id="rag",
            guidelines=[guideline, planner_only],
            human_notes=["Use more cricket examples."],
        ),
    )
