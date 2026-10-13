"""Deterministic stand-ins for Azure chat models so the whole system is testable offline."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

ScriptItem = AIMessage | BaseModel | dict | str | Exception | Callable[[list[BaseMessage]], Any]


def tool_call_message(
    name: str, args: dict[str, Any], *, content: str = "", call_id: str | None = None
) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": call_id or f"call_{uuid.uuid4().hex[:8]}",
                "type": "tool_call",
            }
        ],
    )


def multi_tool_call_message(
    calls: list[tuple[str, dict[str, Any]]], *, content: str = ""
) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[
            {"name": n, "args": a, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}
            for n, a in calls
        ],
    )


class ScriptedChatModel(BaseChatModel):
    """Pops scripted replies in order.

    * ``AIMessage``/``str`` items answer normal (tool-calling) invocations.
    * ``BaseModel``/``dict`` items answer ``with_structured_output`` invocations.
    * Callables receive the messages and return one of the above (for assertions).
    * Exceptions are raised (to test retries/fallbacks).
    """

    model_name: str = "scripted-model"
    script: list[Any] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)
    usage: dict[str, Any] | None = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _pop(self, messages: list[BaseMessage]) -> Any:
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError(
                f"{self.model_name}: script exhausted after {len(self.calls)} calls"
            )
        item = self.script.pop(0)
        if callable(item) and not isinstance(item, (BaseModel, AIMessage)):
            item = item(list(messages))
        if isinstance(item, Exception):
            raise item
        return item

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        item = self._pop(messages)
        if isinstance(item, str):
            item = AIMessage(content=item)
        if not isinstance(item, AIMessage):
            raise TypeError(f"expected AIMessage for a chat call, got {type(item).__name__}")
        if self.usage and item.usage_metadata is None:
            item.usage_metadata = dict(self.usage)  # type: ignore[assignment]
        return ChatResult(
            generations=[ChatGeneration(message=item)],
            llm_output={"model_name": self.model_name},
        )

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:  # type: ignore[override]
        self.bound_tools = list(tools)
        return self

    def with_structured_output(  # type: ignore[override]
        self, schema: Any, *, include_raw: bool = False, **kwargs: Any
    ) -> RunnableLambda:
        def _invoke(input_: Any) -> Any:
            messages = self._convert_input(input_).to_messages()
            item = self._pop(messages)
            parsed = item if isinstance(item, schema) else schema.model_validate(item)
            if include_raw:
                return {
                    "raw": AIMessage(content=parsed.model_dump_json()),
                    "parsed": parsed,
                    "parsing_error": None,
                }
            return parsed

        return RunnableLambda(_invoke)
