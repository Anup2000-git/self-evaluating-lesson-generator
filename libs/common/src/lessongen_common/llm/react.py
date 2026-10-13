r"""A small, explicit ReAct agent built from LangGraph primitives.

    START -> agent --(tool calls)--> tools --(no submission yet)--> agent ...
                  \                      \--(valid submission)--> END
                   \--(budget exhausted)--> force_submit --> END

Why not ``create_react_agent``? We need three guarantees the prebuilt agent does not give
out of the box, and they are the whole point of a production agent:

1. **Typed final answer.** The agent finishes only by calling a ``submit_*`` tool whose
   arguments are validated with Pydantic plus a business validator. Invalid submissions are
   rejected with the exact problems, so the agent fixes them itself (self-correction).
2. **Hard step budget.** After ``max_steps`` model turns we force a structured final
   answer, so the loop always terminates and cost is bounded.
3. **Observable reasoning.** Every tool takes a ``reason`` argument; together with tool
   results this is streamed as Thought -> Action -> Observation events for the UI.
"""

from __future__ import annotations

import asyncio
import json
import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ValidationError

from lessongen_common.errors import AgentError
from lessongen_common.events import emit
from lessongen_common.llm.provider import LLMProvider
from lessongen_common.llm.structured import invoke_structured
from lessongen_common.logs import get_logger
from lessongen_common.schemas.events import EventType

log = get_logger(__name__)


@dataclass
class AgentTool[A: BaseModel]:
    """A research/utility tool. ``args_schema`` must contain a ``reason: str`` field."""

    name: str
    description: str
    args_schema: type[A]
    func: Callable[[A], Awaitable[str]]
    preview: Callable[[str], str] = field(default=lambda result: result[:300])

    def openai_spec(self) -> dict[str, Any]:
        spec = convert_to_openai_tool(self.args_schema)
        spec["function"]["name"] = self.name
        spec["function"]["description"] = self.description
        return spec


@dataclass
class SubmitTool[T: BaseModel]:
    """The tool that ends the loop. ``validate`` returns a list of problems (empty = accept)."""

    name: str
    description: str
    schema: type[T]
    validate: Callable[[T], list[str]] = field(default=lambda _obj: [])
    summarize: Callable[[T], dict[str, Any]] = field(default=lambda _obj: {})

    def openai_spec(self) -> dict[str, Any]:
        spec = convert_to_openai_tool(self.schema)
        spec["function"]["name"] = self.name
        spec["function"]["description"] = self.description
        return spec


@dataclass
class AgentResult[T: BaseModel]:
    output: T
    steps: int
    forced: bool
    rejected_submissions: int


class _State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    steps: int
    rejected: Annotated[int, operator.add]
    submission: dict[str, Any] | None
    forced: bool


def _text_of(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts).strip()


class ReactAgent[T: BaseModel]:
    def __init__(
        self,
        *,
        name: str,
        model: BaseChatModel,
        tools: list[AgentTool[Any]],
        submit: SubmitTool[T],
        provider: LLMProvider | None = None,
        max_steps: int = 10,
        max_rejections: int = 3,
    ) -> None:
        self.name = name
        self.model = model
        self.tools = {t.name: t for t in tools}
        self.submit = submit
        self.provider = provider
        self.max_steps = max_steps
        self.max_rejections = max_rejections
        specs = [t.openai_spec() for t in tools] + [submit.openai_spec()]
        self._bound = model.bind_tools(specs, tool_choice="required")
        self.graph = self._build_graph()

    # ------------------------------------------------------------------ graph
    def _build_graph(self) -> Any:
        graph = StateGraph(_State)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._tools_node)
        graph.add_node("force_submit", self._force_submit_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._after_agent, ["tools", "agent", "force_submit"])
        graph.add_conditional_edges("tools", self._after_tools, ["agent", "force_submit", END])
        graph.add_edge("force_submit", END)
        return graph.compile(name=self.name)

    async def _agent_node(self, state: _State) -> dict[str, Any]:
        if self.provider is not None:
            async with self.provider.slot():
                ai = await self._bound.ainvoke(state["messages"])
        else:
            ai = await self._bound.ainvoke(state["messages"])
        thought = _text_of(ai)
        if thought:
            await emit(EventType.AGENT_THOUGHT, {"agent": self.name, "text": thought[:1200]})
        update: dict[str, Any] = {"messages": [ai], "steps": state["steps"] + 1}
        if not ai.tool_calls and not ai.invalid_tool_calls:
            update["messages"].append(
                HumanMessage(
                    content=f"Always respond with a tool call. When you are ready, call `{self.submit.name}`."
                )
            )
        return update

    def _after_agent(self, state: _State) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and (last.tool_calls or last.invalid_tool_calls):
            return "tools"
        return "force_submit" if state["steps"] >= self.max_steps else "agent"

    async def _run_tool(self, call: dict[str, Any]) -> ToolMessage:
        tool = self.tools.get(call["name"])
        if tool is None:
            return ToolMessage(
                content=f"ERROR: unknown tool '{call['name']}'. Available: {sorted(self.tools)}",
                tool_call_id=call["id"],
            )
        try:
            args = tool.args_schema.model_validate(call["args"])
        except ValidationError as exc:
            return ToolMessage(content=f"ERROR: invalid arguments: {exc}", tool_call_id=call["id"])
        public_args = {k: v for k, v in args.model_dump().items() if k != "reason"}
        await emit(
            EventType.AGENT_TOOL_CALL,
            {
                "agent": self.name,
                "tool": tool.name,
                "reason": getattr(args, "reason", ""),
                "args": public_args,
            },
        )
        try:
            result = await tool.func(args)
        except Exception as exc:  # a broken tool must not kill the agent; it can try again
            log.warning("agent_tool_failed", agent=self.name, tool=tool.name, error=str(exc))
            result = f"ERROR: tool failed: {exc}"
        await emit(
            EventType.AGENT_TOOL_RESULT,
            {"agent": self.name, "tool": tool.name, "preview": tool.preview(result)},
        )
        return ToolMessage(content=result, tool_call_id=call["id"])

    async def _tools_node(self, state: _State) -> dict[str, Any]:
        ai = state["messages"][-1]
        assert isinstance(ai, AIMessage)
        research_calls = [c for c in ai.tool_calls if c["name"] != self.submit.name]
        submit_calls = [c for c in ai.tool_calls if c["name"] == self.submit.name]

        messages: list[BaseMessage] = list(
            await asyncio.gather(*(self._run_tool(c) for c in research_calls))
        )
        submission: dict[str, Any] | None = None
        rejected = 0
        # Every tool call id must get a reply, including calls whose JSON arguments were broken.
        for bad in ai.invalid_tool_calls:
            rejected += 1 if bad.get("name") == self.submit.name else 0
            messages.append(
                ToolMessage(
                    content=f"ERROR: your arguments were not valid JSON ({bad.get('error') or 'parse error'}). Call the tool again.",
                    tool_call_id=bad.get("id") or "invalid",
                )
            )
        for call in submit_calls:
            if submission is not None:
                messages.append(
                    ToolMessage(content="IGNORED: already accepted.", tool_call_id=call["id"])
                )
                continue
            problems: list[str]
            try:
                obj = self.submit.schema.model_validate(call["args"])
                problems = self.submit.validate(obj)
            except ValidationError as exc:
                obj, problems = None, [str(exc)[:3000]]
            if problems:
                rejected += 1
                await emit(
                    EventType.AGENT_TOOL_RESULT,
                    {
                        "agent": self.name,
                        "tool": self.submit.name,
                        "preview": "REJECTED: " + "; ".join(problems)[:600],
                    },
                )
                messages.append(
                    ToolMessage(
                        content="REJECTED. Fix these problems and submit again:\n- "
                        + "\n- ".join(problems),
                        tool_call_id=call["id"],
                    )
                )
            else:
                assert obj is not None
                submission = obj.model_dump(mode="json")
                await emit(
                    EventType.AGENT_SUBMITTED,
                    {"agent": self.name, "tool": self.submit.name, **self.submit.summarize(obj)},
                )
                messages.append(ToolMessage(content="ACCEPTED.", tool_call_id=call["id"]))
        return {"messages": messages, "submission": submission, "rejected": rejected}

    def _after_tools(self, state: _State) -> str:
        if state["submission"] is not None:
            return END
        if state["steps"] >= self.max_steps or state["rejected"] > self.max_rejections:
            return "force_submit"
        return "agent"

    async def _force_submit_node(self, state: _State) -> dict[str, Any]:
        await emit(
            EventType.AGENT_THOUGHT,
            {
                "agent": self.name,
                "text": "Step budget reached - forcing a final structured answer.",
            },
        )
        # Re-state the task plus the research notes as plain text: a structured-output call
        # without tool definitions must not contain tool-call messages.
        history = state["messages"]
        task = [m for m in history if not isinstance(m, (AIMessage, ToolMessage))][:2]
        notes = [
            f"[{i}] {_text_of(m)[:2500]}"
            for i, m in enumerate((m for m in history if isinstance(m, ToolMessage)), start=1)
        ]
        messages: list[BaseMessage] = [
            *task,
            HumanMessage(content="Notes from your research so far:\n" + "\n".join(notes[-12:])),
            HumanMessage(
                content=(
                    "Your step budget is used up. Using everything above, produce your final "
                    "answer now as JSON matching the required schema."
                )
            ),
        ]
        obj = await invoke_structured(
            self.provider,
            self.model,
            self.submit.schema,
            messages,
            name=f"{self.name}.force_submit",
        )
        problems = self.submit.validate(obj)
        if problems:
            log.warning("forced_submission_has_problems", agent=self.name, problems=problems[:5])
        await emit(
            EventType.AGENT_SUBMITTED,
            {
                "agent": self.name,
                "tool": self.submit.name,
                "forced": True,
                **self.submit.summarize(obj),
            },
        )
        return {"submission": obj.model_dump(mode="json"), "forced": True}

    # -------------------------------------------------------------------- run
    async def run(self, messages: list[BaseMessage]) -> AgentResult[T]:
        state: _State = {
            "messages": messages,
            "steps": 0,
            "rejected": 0,
            "submission": None,
            "forced": False,
        }
        final = await self.graph.ainvoke(state, config={"recursion_limit": self.max_steps * 3 + 10})
        if final.get("submission") is None:
            raise AgentError(f"{self.name}: finished without a submission")
        return AgentResult(
            output=self.submit.schema.model_validate(final["submission"]),
            steps=final["steps"],
            forced=bool(final.get("forced")),
            rejected_submissions=final.get("rejected", 0),
        )


def dump_json(data: Any, limit: int = 6000) -> str:
    """Compact JSON for tool observations, truncated to keep the context small."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "...(truncated)"
