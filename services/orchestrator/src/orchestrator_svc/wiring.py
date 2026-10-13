"""Builds clients and the LangGraph checkpointer from settings (shared by API and worker)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from lessongen_common.clients import EvaluatorClient, GeneratorClient, KnowledgeClient, MemoryClient
from lessongen_common.http import ServiceClient
from lessongen_common.logs import get_logger
from orchestrator_svc.settings import OrchestratorSettings

log = get_logger(__name__)


@dataclass
class Clients:
    knowledge: KnowledgeClient
    memory: MemoryClient
    generator: GeneratorClient
    evaluator: EvaluatorClient
    http: dict[str, ServiceClient]

    async def aclose(self) -> None:
        for client in self.http.values():
            await client.aclose()


def build_clients(settings: OrchestratorSettings) -> Clients:
    http = {
        "knowledge": ServiceClient(
            "knowledge", settings.knowledge_url, timeout=settings.http_timeout_seconds
        ),
        "memory": ServiceClient(
            "memory", settings.memory_url, timeout=settings.http_timeout_seconds
        ),
        "generator": ServiceClient(
            "generator", settings.generator_url, timeout=settings.generator_timeout_seconds
        ),
        "evaluator": ServiceClient(
            "evaluator", settings.evaluator_url, timeout=settings.evaluator_timeout_seconds
        ),
    }
    return Clients(
        knowledge=KnowledgeClient(http["knowledge"]),
        memory=MemoryClient(
            http["memory"], consolidation_timeout=settings.consolidation_timeout_seconds
        ),
        generator=GeneratorClient(http["generator"], timeout=settings.generator_timeout_seconds),
        evaluator=EvaluatorClient(http["evaluator"], timeout=settings.evaluator_timeout_seconds),
        http=http,
    )


@contextlib.asynccontextmanager
async def checkpointer(settings: OrchestratorSettings) -> AsyncIterator[Any]:
    """Postgres checkpointer (durable, resumable runs); in-memory when disabled (tests/dev)."""
    if not settings.use_checkpointer:
        from langgraph.checkpoint.memory import InMemorySaver

        yield InMemorySaver()
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    async with AsyncConnectionPool(
        conninfo=settings.checkpoint_database_url,
        max_size=max(4, settings.worker_concurrency * 2),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    ) as pool:
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
        log.info("checkpointer_ready", backend="postgres")
        yield saver
