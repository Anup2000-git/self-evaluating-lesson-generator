"""Run progress events on Redis Streams.

Every service appends events to ``events:run:{run_id}``. The orchestrator API tails that
stream for Server-Sent Events, so the UI can show the generator's and evaluator's ReAct
steps live even though they run in other containers. Streams are replayable from any id
(``Last-Event-ID``), which makes browser reconnects lossless.

Events are telemetry: publishing is best-effort and never fails the business operation.
Durable results (attempts, evaluations) are stored by the memory service.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from lessongen_common.context import get_context
from lessongen_common.logs import get_logger
from lessongen_common.schemas.events import Event

log = get_logger(__name__)


def stream_key(run_id: str) -> str:
    return f"events:run:{run_id}"


class EventBus:
    def __init__(
        self,
        redis: Redis | None,
        service: str,
        *,
        maxlen: int = 5000,
        ttl_seconds: int = 30 * 24 * 3600,
    ) -> None:
        self.redis = redis
        self.service = service
        self.maxlen = maxlen
        self.ttl_seconds = ttl_seconds

    async def publish(
        self,
        run_id: str,
        type: str,
        data: dict[str, Any] | None = None,
        *,
        node: str | None = None,
        attempt: int | None = None,
    ) -> str | None:
        event = Event(
            run_id=run_id,
            ts=datetime.now(UTC),
            service=self.service,
            type=type,
            node=node,
            attempt=attempt,
            data=data or {},
        )
        if self.redis is None:
            return None
        key = stream_key(run_id)
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.xadd(
                    key, {"event": event.model_dump_json()}, maxlen=self.maxlen, approximate=True
                )
                pipe.expire(key, self.ttl_seconds)
                entry_id, _ = await pipe.execute()
            return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        except Exception as exc:  # telemetry must never break the pipeline
            log.warning("event_publish_failed", event_type=type, error=str(exc))
            return None

    async def read(
        self, run_id: str, last_id: str = "0-0", *, block_ms: int | None = None, count: int = 200
    ) -> list[Event]:
        if self.redis is None:
            return []
        response = await self.redis.xread(
            {stream_key(run_id): last_id}, block=block_ms, count=count
        )
        events: list[Event] = []
        for _stream, entries in response or []:
            for entry_id, fields in entries:
                raw = fields.get(b"event") or fields.get("event")
                if raw is None:
                    continue
                payload = json.loads(raw)
                payload["id"] = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                events.append(Event.model_validate(payload))
        return events


_bus: EventBus | None = None


def configure_event_bus(bus: EventBus | None) -> None:
    global _bus
    _bus = bus


def get_event_bus() -> EventBus | None:
    return _bus


async def emit(type: str, data: dict[str, Any] | None = None, *, node: str | None = None) -> None:
    """Publish an event for the run in the current context (no-op outside a run)."""
    ctx = get_context()
    if _bus is None or not ctx.run_id:
        return
    await _bus.publish(ctx.run_id, type, data, node=node or ctx.node, attempt=ctx.attempt)
