"""Run jobs on a Redis Stream consumer group.

* The API appends a job (XADD) and returns immediately.
* Workers read with XREADGROUP; a job is acknowledged (XACK) only when the run reaches a
  terminal state, so a crashed worker leaves it pending.
* A running worker holds ``lock:run:{id}`` and refreshes it (heartbeat). Workers
  periodically XAUTOCLAIM jobs that have been idle too long; if the lock has expired the
  owner is gone and the job is resumed from its last LangGraph checkpoint.
* Cancellation is a flag (``cancel:run:{id}``) checked before every graph node.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from lessongen_common.schemas import Lesson, RunMode


class Job(BaseModel):
    run_id: str
    mode: RunMode
    topic: str
    topic_id: str
    topic_title: str
    helper_language: str
    max_retries: int
    initial_lesson: Lesson | None = None
    fault_id: str | None = None


def lock_key(run_id: str) -> str:
    return f"lock:run:{run_id}"


def cancel_key(run_id: str) -> str:
    return f"cancel:run:{run_id}"


class JobQueue:
    def __init__(self, redis: Redis, stream: str, group: str) -> None:
        self.redis = redis
        self.stream = stream
        self.group = group

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, job: Job) -> str:
        entry = await self.redis.xadd(self.stream, {"job": job.model_dump_json()})
        return entry.decode() if isinstance(entry, bytes) else str(entry)

    async def read(self, consumer: str, count: int, block_ms: int) -> list[tuple[str, Job]]:
        response = await self.redis.xreadgroup(
            self.group, consumer, {self.stream: ">"}, count=count, block=block_ms
        )
        return self._parse(response)

    async def reclaim(
        self, consumer: str, min_idle_ms: int, count: int = 10
    ) -> list[tuple[str, Job]]:
        result = await self.redis.xautoclaim(
            self.stream,
            self.group,
            consumer,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=count,
        )
        claimed = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else []
        return self._parse([[self.stream, claimed]])

    async def ack(self, entry_id: str) -> None:
        await self.redis.xack(self.stream, self.group, entry_id)

    async def depth(self) -> dict[str, int]:
        length = await self.redis.xlen(self.stream)
        try:
            pending = await self.redis.xpending(self.stream, self.group)
            pending_count = (
                int(pending.get("pending", 0)) if isinstance(pending, dict) else int(pending[0])
            )
        except ResponseError:
            pending_count = 0
        return {"stream_length": int(length), "pending": pending_count}

    @staticmethod
    def _parse(response: Any) -> list[tuple[str, Job]]:
        jobs: list[tuple[str, Job]] = []
        for _stream, entries in response or []:
            for entry_id, fields in entries or []:
                if not fields:
                    continue
                raw = fields.get(b"job") or fields.get("job")
                if raw is None:
                    continue
                eid = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                jobs.append((eid, Job.model_validate_json(raw)))
        return jobs
