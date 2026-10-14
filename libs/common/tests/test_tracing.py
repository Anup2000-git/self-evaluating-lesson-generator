import uuid
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langfuse import Langfuse
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel

from lessongen_common.context import (
    HEADER_TRACEPARENT,
    bind_context,
    context_from_headers,
    outgoing_headers,
)
from lessongen_common.llm import AgentTool, ReactAgent, SubmitTool
from lessongen_common.testing import ScriptedChatModel, tool_call_message
from lessongen_common.tracing import Tracer, TracingSettings, trace_id_for_run


def _settings(**overrides: Any) -> TracingSettings:
    values: dict[str, Any] = {
        "public_key": f"pk-lf-test-{uuid.uuid4().hex}",  # one SDK resource manager per test
        "secret_key": "sk-lf-test",
        "project_id": "lessongen",
        "tracing_enabled": True,
    }
    values.update(overrides)
    return TracingSettings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def traced(monkeypatch: pytest.MonkeyPatch) -> Any:
    # The root conftest switches tracing off for the suite; the SDK honours that variable too.
    monkeypatch.delenv("LANGFUSE_TRACING_ENABLED", raising=False)
    exporter = InMemorySpanExporter()
    tracer = Tracer(
        "evaluator", _settings(), tracer_provider=TracerProvider(), span_exporter=exporter
    )
    assert tracer.enabled

    def finished() -> list[ReadableSpan]:
        tracer.flush()
        return list(exporter.get_finished_spans())

    yield tracer, finished
    tracer.shutdown()


def _hex_trace(span: ReadableSpan) -> str:
    return f"{span.context.trace_id:032x}"


def _by_name(spans: list[ReadableSpan], name: str) -> ReadableSpan:
    return next(s for s in spans if s.name == name)


def test_trace_id_matches_the_langfuse_sdk() -> None:
    assert trace_id_for_run("run-42") == Langfuse.create_trace_id(seed="run-42")


async def test_without_keys_everything_is_a_no_op() -> None:
    tracer = Tracer("generator", TracingSettings(_env_file=None))  # type: ignore[call-arg]
    assert not tracer.enabled
    with tracer.span("generator.write") as span:
        span.update(output={"ok": True})
    assert span.trace_id is None
    assert tracer.trace_url("run-1") is None
    assert await tracer.health() == {"enabled": False}


def test_trace_url_points_at_the_runs_trace() -> None:
    settings = _settings(ui_url="http://localhost:3000/")
    assert settings.trace_url("run-7") == (
        f"http://localhost:3000/project/lessongen/traces/{trace_id_for_run('run-7')}"
    )


async def test_llm_calls_inside_an_operation_land_in_the_runs_trace(traced: Any) -> None:
    tracer, finished = traced
    model = ScriptedChatModel(script=[AIMessage(content="PASS")])
    with (
        bind_context(run_id="run-123", attempt=1),
        tracer.span("evaluator.evaluate", as_type="evaluator") as span,
    ):
        await model.ainvoke([HumanMessage(content="Is the lesson accurate?")])
        span.update(output={"passed": True})
    # Outside an operation nothing is captured.
    await ScriptedChatModel(script=[AIMessage(content="x")]).ainvoke("untraced")

    spans = finished()
    operation = _by_name(spans, "evaluator.evaluate")
    generations = [
        s for s in spans if s.attributes.get("langfuse.observation.type") == "generation"
    ]
    assert len(generations) == 1
    assert generations[0].parent is not None
    assert generations[0].parent.span_id == operation.context.span_id
    assert {_hex_trace(s) for s in spans} == {trace_id_for_run("run-123")}
    assert operation.attributes["session.id"] == "run-123"
    assert operation.attributes["langfuse.observation.type"] == "evaluator"
    assert str(operation.attributes["langfuse.observation.metadata.attempt"]) == "1"


async def test_service_span_nests_under_the_callers_node_span(traced: Any) -> None:
    tracer, finished = traced
    # Orchestrator side: a node span; the outgoing call carries it as traceparent.
    with (
        bind_context(run_id="run-9", attempt=1, node="write"),
        tracer.span("write", capture_llm=False),
    ):
        headers = outgoing_headers()
    assert HEADER_TRACEPARENT in headers

    # Service side: the middleware restores the context from the headers.
    incoming = context_from_headers(headers)
    with (
        bind_context(run_id=incoming.run_id, trace_parent=incoming.trace_parent),
        tracer.span("generator.write", as_type="agent"),
    ):
        pass

    spans = finished()
    node, operation = _by_name(spans, "write"), _by_name(spans, "generator.write")
    assert operation.parent is not None
    assert operation.parent.span_id == node.context.span_id
    assert _hex_trace(node) == _hex_trace(operation) == trace_id_for_run("run-9")


async def test_errors_mark_the_span_and_still_propagate(traced: Any) -> None:
    tracer, finished = traced
    with (
        pytest.raises(RuntimeError, match="boom"),
        bind_context(run_id="run-err"),
        tracer.span("generator.plan"),
    ):
        raise RuntimeError("boom")
    span = _by_name(finished(), "generator.plan")
    assert span.attributes["langfuse.observation.level"] == "ERROR"


class _Query(BaseModel):
    reason: str
    query: str


class _Answer(BaseModel):
    text: str


async def test_react_tool_calls_are_traced_as_tools(traced: Any) -> None:
    tracer, finished = traced

    async def search(args: _Query) -> str:
        return "RAG retrieves documents before it answers."

    agent = ReactAgent(
        name="writer",
        model=ScriptedChatModel(
            script=[
                tool_call_message(
                    "search_knowledge_base", {"reason": "need facts", "query": "rag"}
                ),
                tool_call_message("submit_answer", {"text": "RAG looks things up first."}),
            ]
        ),
        tools=[AgentTool("search_knowledge_base", "Search the KB", _Query, search)],
        submit=SubmitTool("submit_answer", "Submit", _Answer),
    )
    with bind_context(run_id="run-tools"), tracer.span("generator.write", as_type="agent"):
        await agent.run([HumanMessage(content="Explain RAG.")])

    spans = finished()
    tool = _by_name(spans, "search_knowledge_base")
    assert tool.attributes["langfuse.observation.type"] == "tool"
    parent = next(s for s in spans if s.context.span_id == tool.parent.span_id)  # type: ignore[union-attr]
    assert parent.name == "tools"  # nested under the agent graph's tools node
    assert "RAG retrieves documents" in str(tool.attributes["langfuse.observation.output"])
