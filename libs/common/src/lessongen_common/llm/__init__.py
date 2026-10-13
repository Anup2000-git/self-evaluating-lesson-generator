"""LLM plumbing: role-based Azure model provider, usage/cost tracking, structured calls, ReAct."""

from lessongen_common.llm.config import (
    DEFAULT_PRICES,
    ROLE_DEFAULTS,
    LLMRole,
    LLMSettings,
    Price,
    ResolvedRole,
    RoleOverride,
)
from lessongen_common.llm.provider import LLMNotConfiguredError, LLMProvider
from lessongen_common.llm.react import AgentResult, AgentTool, ReactAgent, SubmitTool, dump_json
from lessongen_common.llm.structured import invoke_structured
from lessongen_common.llm.usage import UsageCallback, current_ledger, record_usage, usage_scope

__all__ = [
    "DEFAULT_PRICES",
    "ROLE_DEFAULTS",
    "AgentResult",
    "AgentTool",
    "LLMNotConfiguredError",
    "LLMProvider",
    "LLMRole",
    "LLMSettings",
    "Price",
    "ReactAgent",
    "ResolvedRole",
    "RoleOverride",
    "SubmitTool",
    "UsageCallback",
    "current_ledger",
    "dump_json",
    "invoke_structured",
    "record_usage",
    "usage_scope",
]
