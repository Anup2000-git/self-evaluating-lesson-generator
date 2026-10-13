import httpx
import pytest
from fakeredis import FakeAsyncRedis

from lessongen_common.context import HEADER_RUN_ID, bind_context
from lessongen_common.errors import ServiceError
from lessongen_common.events import EventBus
from lessongen_common.http import ServiceClient
from lessongen_common.rendering import lesson_to_markdown
from lessongen_common.testing import sample_lesson


async def test_service_client_retries_unavailable_then_succeeds() -> None:
    attempts: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.headers.get(HEADER_RUN_ID))
        if len(attempts) < 3:
            return httpx.Response(503, json={"detail": "warming up"})
        return httpx.Response(200, json={"ok": True})

    client = ServiceClient("svc", "http://svc", transport=httpx.MockTransport(handler), retries=3)
    with bind_context(run_id="run-42"):
        assert await client.get("/thing") == {"ok": True}
    assert attempts == ["run-42", "run-42", "run-42"]


async def test_service_client_does_not_retry_server_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"detail": "boom"})

    client = ServiceClient("svc", "http://svc", transport=httpx.MockTransport(handler))
    with pytest.raises(ServiceError) as info:
        await client.post("/x", json={})
    assert (info.value.status, info.value.detail, calls) == (500, "boom", 1)


async def test_event_bus_round_trip() -> None:
    bus = EventBus(FakeAsyncRedis(), "tester")
    first = await bus.publish("r1", "node.started", {"x": 1}, node="plan", attempt=1)
    await bus.publish("r1", "node.completed", {"x": 2}, node="plan", attempt=1)
    events = await bus.read("r1")
    assert [e.type for e in events] == ["node.started", "node.completed"]
    assert events[0].id == first and events[0].service == "tester"
    later = await bus.read("r1", last_id=first)
    assert [e.data["x"] for e in later] == [2]


def test_lesson_markdown_contains_every_part() -> None:
    lesson = sample_lesson()
    md = lesson_to_markdown(lesson)
    assert md.startswith(f"# {lesson.title}")
    for section in lesson.sections:
        assert f"## {section.heading}" in md
    assert "| Word | Simple meaning | Hindi |" in md
    assert "खोज कर लाना" in md
    assert "### Answers" in md
