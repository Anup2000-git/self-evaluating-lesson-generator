"""The Redis-Streams worker and the public API (SSE, cancel, exports) with fakeredis."""

import json

import pytest
from fastapi.testclient import TestClient

from lessongen_common.events import EventBus
from lessongen_common.llm import LLMProvider, LLMSettings
from lessongen_common.schemas import RunMode, RunStatus
from lessongen_common.testing import sample_lesson
from orchestrator_svc.jobs import JobQueue, lock_key
from orchestrator_svc.main import create_app
from orchestrator_svc.worker import Worker


async def _worker(settings, fake_redis, make_pipeline, evaluator, fake_clients, bus):
    graph, _ = make_pipeline(evaluator)
    return Worker(
        settings=settings,
        redis=fake_redis,
        clients=fake_clients,
        graph=graph,
        bus=bus,
        consumer="w1",
    )


async def test_worker_runs_a_job_and_acks_it(
    settings, fake_redis, make_pipeline, evaluator_factory, fake_clients, job_factory, bus
) -> None:
    worker = await _worker(
        settings, fake_redis, make_pipeline, evaluator_factory([["EX-1"], []]), fake_clients, bus
    )
    queue = JobQueue(fake_redis, settings.job_stream, settings.job_group)
    await queue.ensure_group()
    fake_clients.memory.ensure("run_t")
    await queue.enqueue(job_factory())
    [(entry_id, job)] = await queue.read("w1", 1, block_ms=10)
    await worker.process(entry_id, job)

    assert fake_clients.memory.runs["run_t"].status == RunStatus.SHIPPED
    assert bus.types("run_t")[0] == "run.started" and bus.types("run_t")[-1] == "run.completed"
    assert (await queue.depth())["pending"] == 0  # acked
    assert not await fake_redis.exists(lock_key("run_t"))  # lock released


async def test_worker_leaves_jobs_owned_by_a_live_worker(
    settings, fake_redis, make_pipeline, evaluator_factory, fake_clients, job_factory, bus
) -> None:
    evaluator = evaluator_factory([[]])
    worker = await _worker(settings, fake_redis, make_pipeline, evaluator, fake_clients, bus)
    await fake_redis.set(lock_key("run_t"), "other-worker")
    await worker.process("1-0", job_factory(), reclaimed=True)
    assert evaluator.calls == 0


async def test_failed_run_is_marked_failed_and_reported(
    settings, fake_redis, make_pipeline, evaluator_factory, fake_clients, job_factory, bus
) -> None:
    worker = await _worker(
        settings,
        fake_redis,
        make_pipeline,
        evaluator_factory([RuntimeError("boom")]),
        fake_clients,
        bus,
    )
    fake_clients.memory.ensure("run_t")
    await worker.execute(job_factory())
    assert fake_clients.memory.runs["run_t"].status == RunStatus.FAILED
    assert "boom" in fake_clients.memory.runs["run_t"].error
    assert bus.types("run_t")[-1] == "run.failed"


async def test_shutdown_mid_run_leaves_the_job_pending_for_another_worker(
    settings, fake_redis, make_pipeline, fake_clients, job_factory, bus
) -> None:
    import asyncio

    started = asyncio.Event()

    class HangingEvaluator:
        async def evaluate(self, request):
            started.set()
            await asyncio.Event().wait()  # never returns: the worker gets SIGTERM meanwhile

    graph, _ = make_pipeline(HangingEvaluator())
    worker = Worker(
        settings=settings,
        redis=fake_redis,
        clients=fake_clients,
        graph=graph,
        bus=bus,
        consumer="w1",
    )
    queue = JobQueue(fake_redis, settings.job_stream, settings.job_group)
    await queue.ensure_group()
    fake_clients.memory.ensure("run_t")
    await queue.enqueue(job_factory())
    [(entry_id, job)] = await queue.read("w1", 1, block_ms=10)

    task = asyncio.create_task(worker.process(entry_id, job))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (await queue.depth())["pending"] == 1  # NOT acked - it will be reclaimed
    assert not await fake_redis.exists(lock_key("run_t"))  # lock released for a fast takeover
    snapshot = await graph.aget_state({"configurable": {"thread_id": "run_t"}})
    assert snapshot.next == ("evaluate",)  # the next worker resumes exactly here


async def test_abandoned_jobs_are_reclaimed(settings, fake_redis, job_factory) -> None:
    queue = JobQueue(fake_redis, settings.job_stream, settings.job_group)
    await queue.ensure_group()
    await queue.enqueue(job_factory("run_x"))
    assert len(await queue.read("crashed-worker", 1, block_ms=10)) == 1  # read but never acked
    reclaimed = await queue.reclaim("w2", min_idle_ms=0)
    assert [j.run_id for _, j in reclaimed] == ["run_x"]


def _client(settings, fake_clients, fake_redis) -> TestClient:
    settings.events_enabled = True
    app = create_app(
        settings,
        clients=fake_clients,
        llm=LLMProvider(LLMSettings(_env_file=None)),
        redis=fake_redis,
    )  # type: ignore[call-arg]
    return TestClient(app)


def test_create_run_queues_a_job(settings, fake_clients, fake_redis) -> None:
    with _client(settings, fake_clients, fake_redis) as client:
        response = client.post("/v1/runs", json={"topic": "Introduction to RAG"})
        assert response.status_code == 202
        run = response.json()
        assert (
            run["status"] == "queued" and run["topic_id"] == "rag" and run["id"].startswith("run_")
        )
        unknown = client.post("/v1/runs", json={"topic": "Quantum baking"})
        assert unknown.status_code == 422
        assert "No grounded knowledge pack" in unknown.json()["detail"]
        lab = client.post(
            "/v1/runs",
            json={
                "topic": "RAG",
                "mode": "evaluate_only",
                "initial_lesson": sample_lesson().model_dump(mode="json"),
            },
        )
        assert lab.json()["max_retries"] == 0


async def test_events_are_streamed_and_replayable(settings, fake_clients, fake_redis) -> None:
    bus = EventBus(fake_redis, "test")
    await bus.publish("run_s", "node.started", {"node": "plan"})
    await bus.publish("run_s", "run.completed", {"status": "shipped"})
    fake_clients.memory.ensure("run_s")
    with (
        _client(settings, fake_clients, fake_redis) as client,
        client.stream("GET", "/v1/runs/run_s/events") as response,
    ):
        assert response.headers["content-type"].startswith("text/event-stream")
        payloads = [
            json.loads(line[5:]) for line in response.iter_lines() if line.startswith("data:")
        ]
    assert [p["type"] for p in payloads] == ["node.started", "run.completed"]
    assert payloads[0]["id"]  # each event carries its stream id for Last-Event-ID resumes


def test_cancel_exports_and_system_status(settings, fake_clients, fake_redis) -> None:
    memory = fake_clients.memory
    memory.ensure("run_c")
    memory.runs["run_c"] = memory.runs["run_c"].model_copy(update={"status": RunStatus.RUNNING})
    with _client(settings, fake_clients, fake_redis) as client:
        assert client.post("/v1/runs/run_c/cancel").status_code == 202
        memory.runs["run_c"] = memory.runs["run_c"].model_copy(update={"status": RunStatus.SHIPPED})
        assert client.post("/v1/runs/run_c/cancel").status_code == 409
        assert client.get("/v1/runs/run_c/export/lesson.md").status_code == 404  # no attempt yet

        from datetime import UTC, datetime

        from lessongen_common.schemas import AttemptKind, AttemptRecord
        from lessongen_common.testing import sample_report

        memory.attempts["run_c"] = {
            1: AttemptRecord(
                attempt_no=1,
                kind=AttemptKind.INITIAL,
                lesson=sample_lesson(),
                evaluation=sample_report([]),
                created_at=datetime.now(UTC),
            )
        }
        memory.runs["run_c"] = memory.runs["run_c"].model_copy(update={"final_attempt_no": 1})
        lesson_md = client.get("/v1/runs/run_c/export/lesson.md")
        assert lesson_md.headers["content-type"].startswith("text/markdown")
        assert lesson_md.text.startswith("# Introduction to RAG")
        log_md = client.get("/v1/runs/run_c/export/rejection-log.md").text
        assert "# Rejection log" in log_md and "Attempt 1" in log_md

        status = client.get("/v1/system/status").json()
        assert {s["name"] for s in status["services"]} >= {
            "orchestrator-api",
            "knowledge",
            "evaluator",
        }
        assert status["llm"]["configured"] is False
        assert any(r["role"] == "writer" for r in status["llm"]["roles"])
        assert client.get("/v1/topics").json()[0]["id"] == "rag"
        _ = RunMode
