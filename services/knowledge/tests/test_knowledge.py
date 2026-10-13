from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowledge_svc.main import create_app
from knowledge_svc.packs import PackRegistry, _stem_key
from knowledge_svc.settings import PACKAGED_PACKS_DIR, KnowledgeSettings
from lessongen_common.llm import LLMSettings
from lessongen_common.textmetrics import has_script


@pytest.fixture(scope="module")
def registry() -> PackRegistry:
    reg = PackRegistry(PACKAGED_PACKS_DIR)
    reg.load()
    return reg


def test_rag_pack_is_complete_and_consistent(registry: PackRegistry) -> None:
    loaded = registry.get("rag")
    pack = loaded.pack
    assert len(loaded.documents) == 11
    assert len(pack.key_points.how_steps) == 5
    assert len(pack.key_points.why) >= 2
    assert len(pack.learner_questions) == 6
    assert all(d.source for d in loaded.documents)
    # Every glossary item has a Hindi meaning written in Devanagari.
    for item in loaded.glossary:
        assert has_script(item.translations["hindi"], "Hindi"), item.term
    # Every main jargon term can be looked up in the approved glossary.
    lookup = loaded.lookup([j.term for j in pack.jargon])
    assert lookup.missing == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Introduction to RAG", "rag"),
        ("RAG (Retrieval-Augmented Generation)", "rag"),
        ("retrieval augmented generation", "rag"),
        ("rag", "rag"),
        ("Intro to vector databases", None),
        ("How to bake bread", None),
    ],
)
def test_topic_resolution(registry: PackRegistry, text: str, expected: str | None) -> None:
    resolution = registry.resolve(text)
    assert (resolution.topic_id if resolution else None) == expected


@pytest.mark.parametrize(
    ("query", "expected_doc"),
    [
        ("why do LLMs give outdated answers after the knowledge cutoff", "rag/03-why-rag"),
        ("why split documents into small chunks", "rag/06-chunking"),
        ("is RAG the same as fine-tuning the model", "rag/08-rag-vs-fine-tuning"),
        ("what is an embedding vector", "rag/05-embeddings-and-search"),
        ("who introduced retrieval-augmented generation paper", "rag/02-what-is-rag"),
    ],
)
async def test_search_returns_relevant_chunks(
    registry: PackRegistry, query: str, expected_doc: str
) -> None:
    retriever, hits = await registry.search("rag", query, 3)
    assert retriever == "bm25"
    assert hits, query
    assert expected_doc in {h.chunk.doc_id for h in hits}, [h.chunk.id for h in hits]


def test_glossary_lookup_handles_aliases_and_plurals(registry: PackRegistry) -> None:
    result = registry.get("rag").lookup(["embeddings", "LLM", "vector store", "quantum flux"])
    assert [g.term for g in result.found] == [
        "Embedding",
        "Large Language Model",
        "Vector database",
    ]
    assert result.missing == ["quantum flux"]


def test_stem_key_normalises_hyphens_and_case() -> None:
    assert _stem_key("Fine-tuning") == _stem_key("fine tuning")


def test_broken_pack_fails_loudly(tmp_path: Path) -> None:
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "pack.yaml").write_text("id: broken\n", encoding="utf-8")
    with pytest.raises(ValueError):
        PackRegistry(tmp_path).load()


@pytest.fixture(scope="module")
def client() -> TestClient:
    settings = KnowledgeSettings(_env_file=None, events_enabled=False, log_json=False)  # type: ignore[call-arg]
    app = create_app(settings, LLMSettings(_env_file=None))  # type: ignore[call-arg]
    with TestClient(app) as test_client:
        yield test_client


def test_api_topics_and_assessment_privacy(client: TestClient) -> None:
    assert [t["id"] for t in client.get("/v1/topics").json()] == ["rag"]
    public = client.get("/v1/topics/rag").json()
    assert public["learner_questions"] == []
    private = client.get("/v1/topics/rag", params={"include_assessment": True}).json()
    assert len(private["learner_questions"]) == 6


def test_api_resolve_unknown_topic_is_a_clear_404(client: TestClient) -> None:
    response = client.post("/v1/topics/resolve", json={"text": "Quantum cooking"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "No grounded knowledge pack" in response.json()["detail"]


def test_api_search_and_probes(client: TestClient) -> None:
    body = client.post(
        "/v1/search", json={"topic_id": "rag", "query": "what is hallucination", "k": 2}
    ).json()
    assert body["retriever"] == "bm25" and len(body["hits"]) == 2
    assert client.get("/healthz").json()["status"] == "ok"
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["checks"] == {"packs": "ok"}
    assert client.get("/v1/topics/nope").status_code == 404
