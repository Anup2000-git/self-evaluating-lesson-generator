"""One-shot job: apply database migrations, then seed rubric v1 if no rubric exists.

Runs as the ``migrate`` container before the memory service starts (in production this
would be a deploy step / Kubernetes Job, so replicas never race on migrations).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from lessongen_common.logs import configure_logging, get_logger
from lessongen_common.rubric import load_seed_rubric
from memory_svc.db import make_engine, make_session_factory
from memory_svc.repository import MemoryRepository
from memory_svc.settings import MemorySettings

log = get_logger(__name__)


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.attributes["url"] = url
    return cfg


def upgrade(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


async def seed(settings: MemorySettings) -> bool:
    engine = make_engine(settings.database_url)
    try:
        repo = MemoryRepository(make_session_factory(engine), settings)
        return await repo.seed_rubric(load_seed_rubric())
    finally:
        await engine.dispose()


def main() -> None:
    settings = MemorySettings()
    configure_logging("memory-migrate", settings.log_level, settings.log_json)
    upgrade(settings.database_url)
    log.info("migrations_applied")
    seeded = asyncio.run(seed(settings))
    log.info("rubric_seed", seeded=seeded)


if __name__ == "__main__":
    main()
