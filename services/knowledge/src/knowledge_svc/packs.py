"""Loading, validating and querying topic packs.

A pack directory contains ``pack.yaml`` (key points, jargon, assessment), ``glossary.yaml``
(approved definitions with helper-language meanings) and ``docs/*.md`` (curated reference
notes with a ``source`` in their front matter). Packs are validated at startup - a broken
pack fails the service's readiness check instead of silently producing ungrounded lessons.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from knowledge_svc.retriever import BM25Retriever, Retriever
from lessongen_common.errors import NotFoundError
from lessongen_common.logs import get_logger
from lessongen_common.schemas.topic import (
    GlossaryItem,
    GlossaryLookupResponse,
    KBChunk,
    KBDocument,
    SearchHit,
    TopicPack,
    TopicPackSummary,
    TopicResolution,
)
from lessongen_common.textmetrics import stem, words

log = get_logger(__name__)

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class PackError(ValueError):
    pass


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _normalize(text: str) -> str:
    return " ".join(w.lower() for w in words(text.replace("-", " ")))


def _stem_key(text: str) -> tuple[str, ...]:
    return tuple(stem(w) for part in words(text) for w in part.split("-") if w)


def parse_document(path: Path, pack_id: str) -> KBDocument:
    raw = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(raw)
    if not match:
        raise PackError(f"{path.name}: missing front matter with title/source")
    meta = yaml.safe_load(match.group(1)) or {}
    title, source = meta.get("title"), meta.get("source")
    if not title or not source:
        raise PackError(f"{path.name}: front matter needs 'title' and 'source'")
    body = raw[match.end() :]
    doc_id = f"{pack_id}/{path.stem}"
    chunks: list[KBChunk] = []
    for block in re.split(r"(?m)^## ", body):
        block = block.strip()
        if not block:
            continue
        heading, _, text = block.partition("\n")
        text = text.strip()
        if not text:
            continue
        chunks.append(
            KBChunk(
                id=f"{doc_id}#{_slug(heading)}",
                doc_id=doc_id,
                doc_title=str(title),
                heading=heading.strip(),
                text=text,
                source=str(source),
            )
        )
    if not chunks:
        raise PackError(f"{path.name}: no '## ' sections found")
    return KBDocument(id=doc_id, title=str(title), source=str(source), chunks=chunks)


@dataclass
class LoadedPack:
    pack: TopicPack
    glossary: list[GlossaryItem]
    documents: list[KBDocument]
    retriever: Retriever

    @property
    def chunks(self) -> list[KBChunk]:
        return [c for d in self.documents for c in d.chunks]

    def summary(self) -> TopicPackSummary:
        return TopicPackSummary(
            id=self.pack.id,
            title=self.pack.title,
            aliases=self.pack.aliases,
            summary=self.pack.summary,
            version=self.pack.version,
            document_count=len(self.documents),
            chunk_count=len(self.chunks),
        )

    def lookup(self, terms: list[str]) -> GlossaryLookupResponse:
        index: dict[tuple[str, ...], GlossaryItem] = {}
        for item in self.glossary:
            for name in [item.term, *item.aliases]:
                index.setdefault(_stem_key(name), item)
        found: list[GlossaryItem] = []
        missing: list[str] = []
        for term in terms:
            item = index.get(_stem_key(term))
            if item is None:
                best = max(
                    self.glossary,
                    key=lambda g: fuzz.ratio(_normalize(term), _normalize(g.term)),
                    default=None,
                )
                if best and fuzz.ratio(_normalize(term), _normalize(best.term)) >= 90:
                    item = best
            if item is None:
                missing.append(term)
            elif item not in found:
                found.append(item)
        return GlossaryLookupResponse(found=found, missing=missing)


def load_pack(directory: Path) -> tuple[TopicPack, list[GlossaryItem], list[KBDocument]]:
    pack_file = directory / "pack.yaml"
    if not pack_file.exists():
        raise PackError(f"{directory.name}: pack.yaml not found")
    pack = TopicPack.model_validate(yaml.safe_load(pack_file.read_text(encoding="utf-8")))
    if pack.id != directory.name:
        raise PackError(f"pack id '{pack.id}' must match its folder name '{directory.name}'")
    glossary_file = directory / "glossary.yaml"
    glossary = (
        [
            GlossaryItem.model_validate(g)
            for g in yaml.safe_load(glossary_file.read_text(encoding="utf-8"))
        ]
        if glossary_file.exists()
        else []
    )
    doc_files = sorted((directory / "docs").glob("*.md"))
    if not doc_files:
        raise PackError(f"{pack.id}: no documents in docs/")
    documents = [parse_document(path, pack.id) for path in doc_files]
    if len(pack.learner_questions) < 3:
        raise PackError(f"{pack.id}: needs at least 3 held-out learner questions")
    return pack, glossary, documents


class PackRegistry:
    def __init__(self, packs_dir: Path) -> None:
        self.packs_dir = packs_dir
        self.packs: dict[str, LoadedPack] = {}
        self.error: str | None = None

    def load(self) -> None:
        loaded: dict[str, LoadedPack] = {}
        try:
            for directory in sorted(p for p in self.packs_dir.iterdir() if p.is_dir()):
                pack, glossary, documents = load_pack(directory)
                chunks = [c for d in documents for c in d.chunks]
                loaded[pack.id] = LoadedPack(pack, glossary, documents, BM25Retriever(chunks))
                log.info(
                    "pack_loaded", topic_id=pack.id, documents=len(documents), chunks=len(chunks)
                )
        except (PackError, ValueError, OSError) as exc:
            self.error = str(exc)
            log.error("pack_load_failed", error=self.error)
            raise
        if not loaded:
            self.error = f"no topic packs found in {self.packs_dir}"
            raise PackError(self.error)
        self.packs = loaded
        self.error = None

    async def ready(self) -> None:
        if self.error or not self.packs:
            raise RuntimeError(self.error or "packs not loaded")

    def get(self, topic_id: str) -> LoadedPack:
        try:
            return self.packs[topic_id]
        except KeyError:
            raise NotFoundError(
                f"unknown topic '{topic_id}'; available: {sorted(self.packs)}"
            ) from None

    def resolve(self, text: str) -> TopicResolution | None:
        query = _normalize(text)
        for loaded in self.packs.values():
            names = {
                _normalize(a) for a in [loaded.pack.id, loaded.pack.title, *loaded.pack.aliases]
            }
            if query in names:
                return TopicResolution(
                    topic_id=loaded.pack.id, title=loaded.pack.title, confidence=1.0
                )
        best: tuple[float, LoadedPack] | None = None
        for loaded in self.packs.values():
            for alias in [loaded.pack.title, *loaded.pack.aliases]:
                score = float(fuzz.token_set_ratio(query, _normalize(alias)))
                if best is None or score > best[0]:
                    best = (score, loaded)
        if best and best[0] >= 85:
            return TopicResolution(
                topic_id=best[1].pack.id,
                title=best[1].pack.title,
                confidence=round(best[0] / 100, 2),
            )
        return None

    async def search(self, topic_id: str, query: str, k: int) -> tuple[str, list[SearchHit]]:
        loaded = self.get(topic_id)
        return loaded.retriever.name, await loaded.retriever.search(query, k)
