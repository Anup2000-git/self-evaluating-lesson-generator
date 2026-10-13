from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import (
    AttemptKind,
    AttemptRecord,
    RevisionNote,
    RunCreate,
    RunMode,
    RunStatus,
    RunUpdate,
)
from lessongen_common.testing import sample_lesson, sample_report
from memory_svc.db import make_engine, make_session_factory
from memory_svc.models import Base
from memory_svc.repository import MemoryRepository
from memory_svc.settings import MemorySettings


def sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


@pytest.fixture
def settings(tmp_path: Path) -> MemorySettings:
    return MemorySettings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=sqlite_url(tmp_path / "memory.db"),
        events_enabled=False,
        log_json=False,
    )


@pytest.fixture
async def repo(settings: MemorySettings) -> AsyncIterator[MemoryRepository]:
    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repository = MemoryRepository(make_session_factory(engine), settings)
    await repository.seed_rubric(load_seed_rubric())
    yield repository
    await engine.dispose()


def _attempt(
    no: int, failed: list[str], notes: list[tuple[str, str]] | None = None
) -> AttemptRecord:
    return AttemptRecord(
        attempt_no=no,
        kind=AttemptKind.INITIAL if no == 1 else AttemptKind.PATCH,
        lesson=sample_lesson(),
        evaluation=sample_report(failed),
        revision_notes=[RevisionNote(check_id=c, change=t) for c, t in (notes or [])],
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def make_attempt():
    return _attempt


@pytest.fixture
def finish_run():
    return _finished_run


async def _finished_run(
    repo: MemoryRepository,
    run_id: str,
    attempts: list[AttemptRecord],
    *,
    guidelines: list[str] | None = None,
    topic_id: str = "rag",
) -> None:
    await repo.create_run(
        RunCreate(
            id=run_id,
            topic="Introduction to RAG",
            topic_id=topic_id,
            mode=RunMode.GENERATE,
            max_retries=2,
            helper_language="Hindi",
        )
    )
    for a in attempts:
        await repo.save_attempt(run_id, a)
    final = attempts[-1]
    await repo.update_run(
        run_id,
        RunUpdate(
            status=RunStatus.SHIPPED if final.evaluation.passed else RunStatus.NEEDS_HUMAN_REVIEW,
            final_attempt_no=final.attempt_no,
            guideline_ids_applied=guidelines or [],
            finished_at=datetime.now(UTC),
        ),
    )
