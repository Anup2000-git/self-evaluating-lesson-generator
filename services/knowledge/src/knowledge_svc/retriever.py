"""Retrieval over a topic pack's chunks.

Default: BM25 keyword ranking (no extra Azure deployment needed, deterministic, and good
for a small curated corpus). If an embeddings deployment is configured, a dense retriever
is added and both rankings are fused with Reciprocal Rank Fusion (hybrid search) - the
same technique the lessons teach.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

import numpy as np
from rank_bm25 import BM25Okapi

from lessongen_common.logs import get_logger
from lessongen_common.schemas.topic import KBChunk, SearchHit
from lessongen_common.textmetrics import stem, words

log = get_logger(__name__)

_STOPWORDS = frozenset(
    """
    a an and are as at be but by can do does for from has have how i if in into is it its
    me my of on or our so than that the their them then there these they this to us was
    we what when where which who why will with you your
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in words(text) if w.lower() not in _STOPWORDS]


def _chunk_text(chunk: KBChunk) -> str:
    return f"{chunk.doc_title}. {chunk.heading}. {chunk.text}"


class Retriever(Protocol):
    name: str

    async def search(self, query: str, k: int) -> list[SearchHit]: ...


class BM25Retriever:
    name = "bm25"

    def __init__(self, chunks: list[KBChunk]) -> None:
        self.chunks = chunks
        self._bm25 = BM25Okapi([tokenize(_chunk_text(c)) for c in chunks])

    def rank(self, query: str) -> list[tuple[int, float]]:
        terms = tokenize(query)
        if not terms:
            return []
        scores = self._bm25.get_scores(terms)
        order = sorted(range(len(scores)), key=lambda i: float(scores[i]), reverse=True)
        return [(i, float(scores[i])) for i in order if float(scores[i]) != 0.0]

    async def search(self, query: str, k: int) -> list[SearchHit]:
        return [
            SearchHit(chunk=self.chunks[i], score=round(score, 4))
            for i, score in self.rank(query)[:k]
        ]


EmbedMany = Callable[[list[str]], Awaitable[list[list[float]]]]
EmbedOne = Callable[[str], Awaitable[list[float]]]


class DenseRetriever:
    name = "embeddings"

    def __init__(self, chunks: list[KBChunk], embed_query: EmbedOne) -> None:
        self.chunks = chunks
        self._embed_query = embed_query
        self._matrix: np.ndarray | None = None

    async def build(self, embed_many: EmbedMany, cache_dir: Path | None, model: str) -> None:
        texts = [_chunk_text(c) for c in self.chunks]
        digest = hashlib.sha256(("\n".join(texts) + model).encode()).hexdigest()[:16]
        cache = cache_dir / f"emb-{digest}.json" if cache_dir else None
        vectors: list[list[float]] | None = None
        if cache and cache.exists():
            vectors = json.loads(cache.read_text())
        if vectors is None:
            vectors = await embed_many(texts)
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(vectors))
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self._matrix = matrix / np.clip(norms, 1e-9, None)

    async def rank(self, query: str) -> list[tuple[int, float]]:
        if self._matrix is None:
            return []
        q = np.asarray(await self._embed_query(query), dtype=np.float32)
        q = q / max(float(np.linalg.norm(q)), 1e-9)
        scores = self._matrix @ q
        order = np.argsort(-scores)
        return [(int(i), float(scores[i])) for i in order]

    async def search(self, query: str, k: int) -> list[SearchHit]:
        ranked = await self.rank(query)
        return [SearchHit(chunk=self.chunks[i], score=round(s, 4)) for i, s in ranked[:k]]


class HybridRetriever:
    """Reciprocal Rank Fusion: score = sum(1 / (60 + rank)) over both rankings."""

    name = "hybrid(bm25+embeddings)"

    def __init__(self, bm25: BM25Retriever, dense: DenseRetriever, rrf_k: int = 60) -> None:
        self.bm25 = bm25
        self.dense = dense
        self.rrf_k = rrf_k

    async def search(self, query: str, k: int) -> list[SearchHit]:
        fused: dict[int, float] = {}
        for ranking in (self.bm25.rank(query)[:20], (await self.dense.rank(query))[:20]):
            for rank, (index, _score) in enumerate(ranking, start=1):
                fused[index] = fused.get(index, 0.0) + 1.0 / (self.rrf_k + rank)
        order = sorted(fused, key=fused.__getitem__, reverse=True)[:k]
        return [SearchHit(chunk=self.bm25.chunks[i], score=round(fused[i], 5)) for i in order]
