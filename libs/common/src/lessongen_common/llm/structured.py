"""Schema-validated LLM calls with self-correction.

Uses Azure/OpenAI structured outputs (``json_schema``). If the reply still fails
validation (or is cut off), the error is shown to the model and it gets another try.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from lessongen_common.errors import StructuredOutputError
from lessongen_common.llm.provider import LLMProvider
from lessongen_common.logs import get_logger

log = get_logger(__name__)


async def invoke_structured[T: BaseModel](
    provider: LLMProvider | None,
    model: BaseChatModel,
    schema: type[T],
    messages: Sequence[BaseMessage],
    *,
    name: str,
    max_attempts: int = 2,
) -> T:
    runnable = model.with_structured_output(schema, method="json_schema", include_raw=True)
    history: list[BaseMessage] = list(messages)
    last_error = "unknown error"
    for attempt in range(1, max_attempts + 1):
        try:
            if provider is not None:
                async with provider.slot():
                    out: Any = await runnable.ainvoke(history)
            else:
                out = await runnable.ainvoke(history)
        except (ValidationError, ValueError) as exc:  # SDK-side parse failures, length cut-offs
            last_error = str(exc)[:1500]
            out = None
        if isinstance(out, dict):
            parsed = out.get("parsed")
            if isinstance(parsed, schema):
                return parsed
            if isinstance(parsed, dict):
                try:
                    return schema.model_validate(parsed)
                except ValidationError as exc:
                    last_error = str(exc)[:1500]
            elif out.get("parsing_error") is not None:
                last_error = str(out["parsing_error"])[:1500]
        elif isinstance(out, schema):
            return out
        log.warning("structured_output_invalid", call=name, attempt=attempt, error=last_error)
        history = [
            *messages,
            HumanMessage(
                content=(
                    "Your previous reply did not match the required JSON schema. "
                    f"Error: {last_error}\nReturn the complete answer again as valid JSON."
                )
            ),
        ]
    raise StructuredOutputError(
        f"{name}: no valid structured output after {max_attempts} tries: {last_error}"
    )
