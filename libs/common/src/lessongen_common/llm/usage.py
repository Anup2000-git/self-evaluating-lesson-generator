"""Per-request token/cost accounting via a LangChain callback.

Every chat model built by the provider carries ``UsageCallback``. The callback adds each
call's usage to the ledger of the innermost ``usage_scope()``; when a scope closes its
totals roll up into the enclosing scope. Services return the ledger with their response,
so the orchestrator can show cost per node, per attempt and per run.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from lessongen_common.llm.config import LLMSettings
from lessongen_common.logs import get_logger
from lessongen_common.schemas.usage import ModelUsage, Usage

log = get_logger(__name__)

_ledger: ContextVar[Usage | None] = ContextVar("lessongen_usage_ledger", default=None)
_warned_models: set[str] = set()


@contextlib.contextmanager
def usage_scope() -> Iterator[Usage]:
    parent = _ledger.get()
    ledger = Usage()
    token = _ledger.set(ledger)
    try:
        yield ledger
    finally:
        _ledger.reset(token)
        if parent is not None:
            parent.add(ledger)


def current_ledger() -> Usage | None:
    return _ledger.get()


def _model_key(model_name: str) -> str:
    # 'gpt-5.5-2026-04-24' -> 'gpt-5.5' for readable breakdowns; keeps unknown names as-is.
    parts = model_name.split("-")
    if len(parts) > 3 and parts[-3].isdigit() and len(parts[-3]) == 4:
        return "-".join(parts[:-3])
    return model_name


class UsageCallback(AsyncCallbackHandler):
    run_inline = True

    def __init__(self, deployment: str, settings: LLMSettings) -> None:
        self.deployment = deployment
        self.settings = settings

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        llm_output = response.llm_output or {}
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) if message else None
                if not usage:
                    continue
                model_name = (
                    llm_output.get("model_name")
                    or (message.response_metadata or {}).get("model_name")
                    or self.deployment
                )
                record_usage(model_name, usage, self.settings)


def record_usage(model_name: str, usage: dict[str, Any], settings: LLMSettings) -> ModelUsage:
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    input_details = usage.get("input_token_details") or {}
    output_details = usage.get("output_token_details") or {}
    cached = int(input_details.get("cache_read", 0) or 0)
    reasoning = int(output_details.get("reasoning", 0) or 0)

    price = settings.price_for(model_name)
    cost = 0.0
    if price is None:
        if model_name not in _warned_models:
            _warned_models.add(model_name)
            log.warning("no_price_for_model", model=model_name)
    else:
        cost = (
            (input_tokens - cached) * price.input
            + cached * price.cached_input
            + output_tokens * price.output
        ) / 1_000_000

    call = ModelUsage(
        llm_calls=1,
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
        cost_usd=round(cost, 6),
    )
    ledger = _ledger.get()
    if ledger is not None:
        ledger.add_call(_model_key(model_name), call)
    return call
