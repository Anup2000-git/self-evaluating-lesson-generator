"""Shared fixtures: the real RAG topic pack, the seed rubric and scripted fake models."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from langchain_core.messages import BaseMessage

from evaluator_svc.context import EvalContext
from evaluator_svc.settings import EvaluatorSettings
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import KBChunk, Lesson, SearchHit, SearchResponse, TopicPack
from lessongen_common.testing import sample_lesson

PACK_FILE = (
    Path(__file__).resolve().parents[2]
    / "knowledge"
    / "src"
    / "knowledge_svc"
    / "packs"
    / "rag"
    / "pack.yaml"
)


@pytest.fixture(scope="session")
def rag_pack() -> TopicPack:
    return TopicPack.model_validate(yaml.safe_load(PACK_FILE.read_text(encoding="utf-8")))


@pytest.fixture
def settings() -> EvaluatorSettings:
    return EvaluatorSettings(_env_file=None, events_enabled=False, log_json=False)  # type: ignore[call-arg]


@pytest.fixture
def make_ctx(rag_pack: TopicPack) -> Callable[..., EvalContext]:
    def build(lesson: Lesson | None = None, helper_language: str = "Hindi") -> EvalContext:
        return EvalContext(
            lesson=lesson or sample_lesson(),
            topic=rag_pack,
            rubric=load_seed_rubric(),
            helper_language=helper_language,
        )

    return build


class FakeKnowledge:
    """Stands in for the knowledge service: returns the real pack and one canned chunk."""

    def __init__(self, pack: TopicPack) -> None:
        self.pack = pack
        self.queries: list[str] = []

    async def topic(self, topic_id: str, *, include_assessment: bool = False) -> TopicPack:
        return (
            self.pack
            if include_assessment
            else self.pack.model_copy(update={"learner_questions": []})
        )

    async def search(self, topic_id: str, query: str, k: int = 4) -> SearchResponse:
        self.queries.append(query)
        chunk = KBChunk(
            id="rag/11-misconceptions#rag-teaches-the-model-new-facts-permanently",
            doc_id="rag/11-misconceptions",
            doc_title="Common misconceptions about RAG",
            heading="RAG teaches the model new facts permanently",
            text="False. RAG does not retrain the model or change its weights.",
            source="curated",
        )
        return SearchResponse(
            topic_id=topic_id,
            query=query,
            retriever="bm25",
            hits=[SearchHit(chunk=chunk, score=3.2)],
        )


class FakeRubrics:
    async def get(self, version: int | None = None):
        return load_seed_rubric()


@pytest.fixture
def fake_knowledge(rag_pack: TopicPack) -> FakeKnowledge:
    return FakeKnowledge(rag_pack)


@pytest.fixture
def fake_rubrics() -> FakeRubrics:
    return FakeRubrics()


@pytest.fixture
def responder():
    return judge_responder


def check_id_of(messages: list[BaseMessage]) -> str | None:
    match = re.search(r"# Checkpoint (\S+) -", str(messages[-1].content))
    return match.group(1) if match else None


def judge_responder(
    fail: set[str] | None = None, crash: set[str] | None = None
) -> Callable[[list[BaseMessage]], Any]:
    """A judge that PASSes every check except ``fail`` (FAIL) and ``crash`` (raises)."""
    fail = fail or set()
    crash = crash or set()

    def respond(messages: list[BaseMessage]) -> dict[str, Any]:
        text = str(messages[-1].content)
        if "Grade a beginner's answers" in text:
            ids = re.findall(r"^## (Q\d+)", text, flags=re.MULTILINE)
            return {
                "grades": [{"question_id": q, "correct": True, "reason": "matches"} for q in ids]
            }
        check = check_id_of(messages) or "?"
        if check in crash:
            raise RuntimeError(f"judge exploded on {check}")
        verdict = "FAIL" if check in fail else "PASS"
        return {
            "evidence": [],
            "reasoning": f"{check} looks {'wrong' if verdict == 'FAIL' else 'fine'}.",
            "verdict": verdict,
            "fix_instruction": f"Fix {check}." if verdict == "FAIL" else "",
        }

    return respond
