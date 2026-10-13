"""Typed clients for the services the evaluator depends on."""

from __future__ import annotations

import time

from lessongen_common.http import ServiceClient
from lessongen_common.logs import get_logger
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import Rubric, RubricVersionInfo, SearchResponse, TopicPack

log = get_logger(__name__)


class KnowledgeClient:
    def __init__(self, client: ServiceClient) -> None:
        self.client = client

    async def topic(self, topic_id: str) -> TopicPack:
        # The evaluator is allowed to see the held-out learner questions.
        data = await self.client.get(f"/v1/topics/{topic_id}", params={"include_assessment": True})
        return TopicPack.model_validate(data)

    async def search(self, topic_id: str, query: str, k: int = 4) -> SearchResponse:
        data = await self.client.post(
            "/v1/search", json={"topic_id": topic_id, "query": query, "k": k}
        )
        return SearchResponse.model_validate(data)


class RubricProvider:
    """Fetches rubric versions from the memory service, with a short cache.

    If memory is unreachable we fall back to the seed rubric shipped with the code (and say
    so in the logs) so the Evaluator Lab still works; the report is stamped with the version
    that was actually used.
    """

    def __init__(self, client: ServiceClient, cache_seconds: float = 30.0) -> None:
        self.client = client
        self.cache_seconds = cache_seconds
        self._active: tuple[float, Rubric] | None = None
        self._versions: dict[int, Rubric] = {}

    async def get(self, version: int | None = None) -> Rubric:
        if version is not None:
            if version not in self._versions:
                info = RubricVersionInfo.model_validate(
                    await self.client.get(f"/v1/rubric/versions/{version}")
                )
                self._versions[version] = info.rubric
            return self._versions[version]
        now = time.monotonic()
        if self._active and now - self._active[0] < self.cache_seconds:
            return self._active[1]
        try:
            info = RubricVersionInfo.model_validate(await self.client.get("/v1/rubric/active"))
            rubric = info.rubric
        except Exception as exc:
            log.warning("rubric_fallback_to_seed", error=str(exc))
            rubric = load_seed_rubric()
        self._active = (now, rubric)
        return rubric
