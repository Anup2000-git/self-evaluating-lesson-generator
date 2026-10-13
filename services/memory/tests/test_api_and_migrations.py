import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from lessongen_common.llm import LLMProvider, LLMSettings
from lessongen_common.schemas import AttemptKind, AttemptRecord
from lessongen_common.testing import sample_lesson, sample_report
from memory_svc.main import create_app
from memory_svc.migrate import seed, upgrade
from memory_svc.models import Base
from memory_svc.settings import MemorySettings


def _settings(tmp_path: Path) -> MemorySettings:
    return MemorySettings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'm.db').as_posix()}",
        events_enabled=False,
        log_json=False,
    )


def test_alembic_migration_matches_the_models(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    upgrade(settings.database_url)
    assert asyncio.run(seed(settings)) is True
    assert asyncio.run(seed(settings)) is False  # idempotent

    async def columns() -> dict[str, set[str]]:
        engine = create_async_engine(settings.database_url)
        async with engine.connect() as conn:
            result = await conn.run_sync(
                lambda c: {
                    t: {col["name"] for col in inspect(c).get_columns(t)}
                    for t in inspect(c).get_table_names()
                }
            )
        await engine.dispose()
        return result

    migrated = asyncio.run(columns())
    for table in Base.metadata.sorted_tables:
        assert {c.name for c in table.columns} == migrated[table.name], table.name


def test_api_end_to_end(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    upgrade(settings.database_url)
    asyncio.run(seed(settings))
    app = create_app(settings, LLMProvider(LLMSettings(_env_file=None)))  # type: ignore[call-arg]
    with TestClient(app) as client:
        assert client.get("/readyz").json()["checks"]["database"] == "ok"
        created = client.post(
            "/v1/runs",
            json={
                "id": "run_x",
                "topic": "RAG",
                "topic_id": "rag",
                "mode": "generate",
                "max_retries": 2,
                "helper_language": "Hindi",
            },
        )
        assert created.status_code == 201 and created.json()["status"] == "queued"

        record = AttemptRecord(
            attempt_no=1,
            kind=AttemptKind.INITIAL,
            lesson=sample_lesson(),
            evaluation=sample_report(["EX-1"]),
            created_at=datetime.now(UTC),
        )
        saved = client.put("/v1/runs/run_x/attempts/1", json=record.model_dump(mode="json"))
        assert saved.status_code == 200
        patched = client.patch(
            "/v1/runs/run_x", json={"status": "needs_human_review", "final_attempt_no": 1}
        )
        assert patched.json()["status"] == "needs_human_review"

        detail = client.get("/v1/runs/run_x").json()
        assert detail["attempts"][0]["evaluation"]["failed_check_ids"] == ["EX-1"]
        assert client.get("/v1/runs", params={"status": "needs_human_review"}).json()["total"] == 1
        assert client.get("/v1/context", params={"topic_id": "rag"}).json()["topic_id"] == "rag"
        assert client.get("/v1/rubric/active").json()["version"] == 1
        assert client.get("/v1/stats").json()["runs_total"] == 1
        feedback = client.post(
            "/v1/feedback", json={"run_id": "run_x", "rating": "up", "comment": "Nice"}
        )
        assert feedback.status_code == 201
        missing = client.get("/v1/runs/nope")
        assert missing.status_code == 404 and missing.json()["title"] == "Not found"
