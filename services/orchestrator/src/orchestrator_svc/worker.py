"""Orchestrator worker: consumes run jobs and executes the LangGraph pipeline.

Runs in its own container(s) - long LLM runs never block the API, and workers scale out
(``docker compose up --scale orchestrator-worker=3``). Crash safety: jobs are acked only at
a terminal state; an abandoned job is reclaimed and resumed from its last checkpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from lessongen_common.context import bind_context
from lessongen_common.events import EventBus, configure_event_bus
from lessongen_common.logs import configure_logging, get_logger
from lessongen_common.schemas import EventType, RunStatus, RunUpdate
from orchestrator_svc.graph.pipeline import Pipeline, RunCancelled, initial_state
from orchestrator_svc.jobs import Job, JobQueue, cancel_key, lock_key
from orchestrator_svc.settings import OrchestratorSettings
from orchestrator_svc.wiring import Clients, build_clients, checkpointer

log = get_logger(__name__)


class Worker:
    def __init__(
        self,
        *,
        settings: OrchestratorSettings,
        redis: Redis,
        clients: Clients,
        graph: Any,
        bus: EventBus,
        consumer: str | None = None,
    ) -> None:
        self.settings = settings
        self.redis = redis
        self.clients = clients
        self.graph = graph
        self.bus = bus
        self.queue = JobQueue(redis, settings.job_stream, settings.job_group)
        self.consumer = consumer or f"worker-{socket.gethostname()}-{os.getpid()}"
        self._stopping = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    def stop(self) -> None:
        self._stopping.set()

    async def is_cancelled(self, run_id: str) -> bool:
        return bool(await self.redis.exists(cancel_key(run_id)))

    # -------------------------------------------------------------- main loop
    async def run_forever(self) -> None:
        await self.queue.ensure_group()
        log.info(
            "worker_started", consumer=self.consumer, concurrency=self.settings.worker_concurrency
        )
        last_reclaim = 0.0
        loop = asyncio.get_running_loop()
        while not self._stopping.is_set():
            if loop.time() - last_reclaim > 15:
                last_reclaim = loop.time()
                for entry_id, job in await self.queue.reclaim(
                    self.consumer, self.settings.job_reclaim_idle_ms
                ):
                    self._spawn(entry_id, job, reclaimed=True)
            free = self.settings.worker_concurrency - len(self._tasks)
            if free <= 0:
                await asyncio.wait(self._tasks, timeout=2, return_when=asyncio.FIRST_COMPLETED)
                continue
            for entry_id, job in await self.queue.read(self.consumer, free, block_ms=2000):
                self._spawn(entry_id, job)
        if self._tasks:
            log.info("worker_draining", running=len(self._tasks))
            await asyncio.wait(self._tasks, timeout=30)
        log.info("worker_stopped")

    def _spawn(self, entry_id: str, job: Job, reclaimed: bool = False) -> None:
        task = asyncio.create_task(self.process(entry_id, job, reclaimed=reclaimed))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _heartbeat(self, key: str) -> None:
        interval = max(1, self.settings.job_lock_ttl_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            await self.redis.pexpire(key, self.settings.job_lock_ttl_seconds * 1000)

    async def process(self, entry_id: str, job: Job, *, reclaimed: bool = False) -> None:
        key = lock_key(job.run_id)
        acquired = await self.redis.set(
            key, self.consumer, nx=True, px=self.settings.job_lock_ttl_seconds * 1000
        )
        if not acquired:
            if reclaimed:
                log.info("job_still_owned_elsewhere", run_id=job.run_id)
            return  # another live worker owns it; it stays pending until that worker acks
        heartbeat = asyncio.create_task(self._heartbeat(key))
        try:
            await self.execute(job, resumed=reclaimed)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            await self.queue.ack(entry_id)
            owner = await self.redis.get(key)
            if owner in (self.consumer, self.consumer.encode()):
                await self.redis.delete(key)

    # -------------------------------------------------------------- one run
    async def execute(self, job: Job, *, resumed: bool = False) -> dict[str, Any] | None:
        config = {
            "configurable": {"thread_id": job.run_id},
            "recursion_limit": self.settings.recursion_limit,
        }
        snapshot = await self.graph.aget_state(config)
        if snapshot.values and not snapshot.next:
            log.info("run_already_finished", run_id=job.run_id)
            return dict(snapshot.values)
        graph_input = None if snapshot.next else initial_state(job)
        memory = self.clients.memory
        with bind_context(run_id=job.run_id):
            try:
                if graph_input is not None:
                    await memory.update_run(
                        job.run_id,
                        RunUpdate(status=RunStatus.RUNNING, started_at=datetime.now(UTC)),
                    )
                    await self.bus.publish(
                        job.run_id,
                        EventType.RUN_STARTED,
                        {"mode": job.mode.value, "topic": job.topic},
                    )
                else:
                    log.info(
                        "run_resumed_from_checkpoint", run_id=job.run_id, next=list(snapshot.next)
                    )
                    await memory.update_run(
                        job.run_id,
                        RunUpdate(status=RunStatus.RUNNING, status_reason=None, error=None),
                    )
                    await self.bus.publish(
                        job.run_id,
                        EventType.LOG,
                        {
                            "message": f"Resumed from the last checkpoint at node {', '.join(snapshot.next)}"
                        },
                    )
                final = await self.graph.ainvoke(graph_input, config)
                await self.bus.publish(
                    job.run_id,
                    EventType.RUN_COMPLETED,
                    {
                        "status": final.get("status"),
                        "status_reason": final.get("status_reason"),
                        "final_attempt_no": final.get("final_attempt_no"),
                        "attempts": len(final.get("attempts", [])),
                        "cost_usd": round(
                            float((final.get("usage") or {}).get("cost_usd", 0.0)), 4
                        ),
                    },
                )
                return final
            except RunCancelled:
                await memory.update_run(
                    job.run_id,
                    RunUpdate(
                        status=RunStatus.CANCELLED,
                        status_reason="cancelled by user",
                        finished_at=datetime.now(UTC),
                    ),
                )
                await self.bus.publish(job.run_id, EventType.RUN_CANCELLED, {})
                return None
            except Exception as exc:
                log.exception("run_failed", run_id=job.run_id)
                with contextlib.suppress(Exception):
                    await memory.update_run(
                        job.run_id,
                        RunUpdate(
                            status=RunStatus.FAILED,
                            error=f"{type(exc).__name__}: {exc}"[:2000],
                            finished_at=datetime.now(UTC),
                        ),
                    )
                await self.bus.publish(
                    job.run_id,
                    EventType.RUN_FAILED,
                    {"error": f"{type(exc).__name__}: {str(exc)[:500]}"},
                )
                return None


async def main() -> None:
    settings = OrchestratorSettings()
    configure_logging("orchestrator-worker", settings.log_level, settings.log_json)
    redis = Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=3,
    )
    bus = EventBus(
        redis,
        "orchestrator",
        maxlen=settings.event_stream_maxlen,
        ttl_seconds=settings.event_stream_ttl_days * 24 * 3600,
    )
    configure_event_bus(bus)
    clients = build_clients(settings)
    async with checkpointer(settings) as saver:
        holder: dict[str, Worker] = {}

        async def is_cancelled(run_id: str) -> bool:
            return await holder["worker"].is_cancelled(run_id)

        pipeline = Pipeline(
            memory=clients.memory,
            generator=clients.generator,
            evaluator=clients.evaluator,
            settings=settings,
            is_cancelled=is_cancelled,
        )
        worker = Worker(
            settings=settings, redis=redis, clients=clients, graph=pipeline.build(saver), bus=bus
        )
        holder["worker"] = worker
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):  # not available on Windows
                loop.add_signal_handler(sig, worker.stop)
        try:
            await worker.run_forever()
        finally:
            await clients.aclose()
            await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
