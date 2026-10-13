from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from lessongen_common.context import bind_context
from lessongen_common.errors import StructuredOutputError
from lessongen_common.events import EventBus, configure_event_bus
from lessongen_common.llm import (
    AgentTool,
    LLMNotConfiguredError,
    LLMProvider,
    LLMRole,
    LLMSettings,
    ReactAgent,
    SubmitTool,
    invoke_structured,
    record_usage,
    usage_scope,
)
from lessongen_common.testing import ScriptedChatModel, tool_call_message


class SearchArgs(BaseModel):
    reason: str
    query: str


class Answer(BaseModel):
    text: str


class RecordingBus(EventBus):
    def __init__(self) -> None:
        super().__init__(None, "test")
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(
        self, run_id: str, type: str, data: dict | None = None, **kwargs: Any
    ) -> None:  # type: ignore[override]
        self.events.append((type, data or {}))


def _settings(**env: str) -> LLMSettings:
    return LLMSettings(_env_file=None, **env)  # type: ignore[call-arg]


def test_role_defaults_split_writer_and_judges() -> None:
    s = _settings()
    assert s.resolve(LLMRole.WRITER).deployment == "gpt-5.5"
    assert s.resolve(LLMRole.WRITER).reasoning_effort == "medium"
    assert s.resolve(LLMRole.JUDGE).deployment == "gpt-5.4-mini"
    assert s.resolve(LLMRole.JUDGE_TIEBREAK).deployment == "gpt-5.5"
    assert s.resolve(LLMRole.LEARNER).reasoning_effort == "none"


def test_role_overrides_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRIMARY_DEPLOYMENT", "gpt55-prod")
    monkeypatch.setenv("LLM_FAST_DEPLOYMENT", "mini-prod")
    monkeypatch.setenv("LLM_ROLES__FACT_CHECKER__TIER", "primary")
    monkeypatch.setenv("LLM_ROLES__WRITER__REASONING_EFFORT", "high")
    s = LLMSettings(_env_file=None)  # type: ignore[call-arg]
    assert s.resolve(LLMRole.FACT_CHECKER).deployment == "gpt55-prod"
    assert s.resolve(LLMRole.WRITER).reasoning_effort == "high"
    assert s.resolve(LLMRole.JUDGE).deployment == "mini-prod"


def test_price_lookup_uses_longest_prefix() -> None:
    s = _settings()
    assert s.price_for("gpt-5.5-2026-04-24").output == 30.0  # type: ignore[union-attr]
    assert s.price_for("gpt-5.4-mini-2026-03-17").input == 0.75  # type: ignore[union-attr]
    assert s.price_for("unknown-model") is None


def test_usage_scopes_roll_up_with_per_model_breakdown() -> None:
    s = _settings()
    with usage_scope() as outer:
        with usage_scope() as inner:
            record_usage(
                "gpt-5.5-2026-04-24",
                {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "input_token_details": {"cache_read": 200},
                    "output_token_details": {"reasoning": 300},
                },
                s,
            )
        record_usage("gpt-5.4-mini-2026-03-17", {"input_tokens": 1_000_000, "output_tokens": 0}, s)
    # (800 * 5 + 200 * 0.5 + 500 * 30) / 1M
    assert inner.cost_usd == pytest.approx(0.0191)
    assert inner.reasoning_tokens == 300
    assert outer.cost_usd == pytest.approx(0.7691)
    assert set(outer.by_model) == {"gpt-5.5", "gpt-5.4-mini"}
    assert outer.llm_calls == 2


def test_provider_requires_configuration_but_describes_roles() -> None:
    provider = LLMProvider(_settings())
    with pytest.raises(LLMNotConfiguredError):
        provider.get(LLMRole.WRITER)
    roles = {row["role"]: row for row in provider.describe()}
    assert roles["judge"]["deployment"] == "gpt-5.4-mini"
    assert "api_key" not in str(roles)


async def test_invoke_structured_retries_after_invalid_output() -> None:
    model = ScriptedChatModel(script=[{"wrong": 1}, {"text": "ok"}])
    result = await invoke_structured(None, model, Answer, [HumanMessage(content="hi")], name="t")
    assert result.text == "ok"
    retry_prompt = model.calls[1][-1].content
    assert "did not match the required JSON schema" in retry_prompt


async def test_invoke_structured_gives_up() -> None:
    model = ScriptedChatModel(script=[{"wrong": 1}, {"wrong": 2}])
    with pytest.raises(StructuredOutputError):
        await invoke_structured(None, model, Answer, [HumanMessage(content="hi")], name="t")


def _agent(model: ScriptedChatModel, searched: list[str], max_steps: int = 6) -> ReactAgent[Answer]:
    async def search(args: SearchArgs) -> str:
        searched.append(args.query)
        return "RAG retrieves documents before it answers."

    return ReactAgent(
        name="tester",
        model=model,
        tools=[AgentTool("search", "Search the KB", SearchArgs, search)],
        submit=SubmitTool(
            "submit_answer",
            "Submit the final answer",
            Answer,
            validate=lambda a: [] if len(a.text) > 20 else ["answer is too short"],
        ),
        max_steps=max_steps,
    )


async def test_react_agent_researches_self_corrects_and_submits() -> None:
    bus = RecordingBus()
    configure_event_bus(bus)
    searched: list[str] = []
    model = ScriptedChatModel(
        script=[
            tool_call_message(
                "search", {"reason": "I need the definition", "query": "what is rag"}
            ),
            tool_call_message("submit_answer", {"text": "too short"}),
            tool_call_message(
                "submit_answer", {"text": "RAG retrieves documents before answering."}
            ),
        ]
    )
    try:
        with bind_context(run_id="run-1"):
            result = await _agent(model, searched).run(
                [SystemMessage(content="You are a tester."), HumanMessage(content="Explain RAG.")]
            )
    finally:
        configure_event_bus(None)

    assert result.output.text.startswith("RAG retrieves")
    assert (result.steps, result.rejected_submissions, result.forced) == (3, 1, False)
    assert searched == ["what is rag"]
    rejection = [m for m in model.calls[2] if isinstance(m, ToolMessage)][-1]
    assert "answer is too short" in rejection.content
    types = [t for t, _ in bus.events]
    assert types[:2] == ["agent.tool_call", "agent.tool_result"]
    assert types[-1] == "agent.submitted"
    assert bus.events[0][1]["reason"] == "I need the definition"


async def test_react_agent_forces_submission_when_budget_is_spent() -> None:
    searched: list[str] = []
    model = ScriptedChatModel(
        script=[
            tool_call_message("search", {"reason": "r1", "query": "q1"}),
            tool_call_message("search", {"reason": "r2", "query": "q2"}),
            {"text": "Forced answer that is long enough to pass."},
        ]
    )
    result = await _agent(model, searched, max_steps=2).run([HumanMessage(content="Explain RAG.")])
    assert result.forced is True
    assert result.output.text.startswith("Forced answer")
    assert searched == ["q1", "q2"]
    forced_prompt = model.calls[-1]
    assert all(not isinstance(m, ToolMessage) for m in forced_prompt)
    assert "Notes from your research" in forced_prompt[-2].content
