"""LLM configuration: two Azure deployments, many roles.

You configure only ``LLM_PRIMARY_DEPLOYMENT`` (strong model, e.g. GPT-5.5) and
``LLM_FAST_DEPLOYMENT`` (cheaper model, e.g. GPT-5.4-mini). Each role maps to a tier and a
reasoning effort by default; any role can be overridden from the environment, e.g.::

    LLM_ROLES__FACT_CHECKER__TIER=primary
    LLM_ROLES__WRITER__REASONING_EFFORT=high
    LLM_ROLES__JUDGE__DEPLOYMENT=my-other-deployment

Why split roles across models: the writer and the judges are different models, which
reduces self-preference bias (a model grading its own writing), and judging is ~6x cheaper.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMRole(StrEnum):
    PLANNER = "planner"
    WRITER = "writer"
    JUDGE = "judge"
    JUDGE_CONFIRM = "judge_confirm"
    JUDGE_TIEBREAK = "judge_tiebreak"
    FACT_CHECKER = "fact_checker"
    LEARNER = "learner"
    REFLECTOR = "reflector"


Tier = Literal["primary", "fast"]
Effort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]


class RoleDefault(BaseModel):
    tier: Tier
    reasoning_effort: Effort | None
    max_output_tokens: int
    purpose: str


ROLE_DEFAULTS: dict[LLMRole, RoleDefault] = {
    LLMRole.PLANNER: RoleDefault(
        tier="primary",
        reasoning_effort="low",
        max_output_tokens=12000,
        purpose="Outlines the lesson (objectives, sections, analogy, worked example).",
    ),
    LLMRole.WRITER: RoleDefault(
        tier="primary",
        reasoning_effort="medium",
        max_output_tokens=24000,
        purpose="ReAct agent that researches, writes and revises the lesson.",
    ),
    LLMRole.JUDGE: RoleDefault(
        tier="fast",
        reasoning_effort="low",
        max_output_tokens=6000,
        purpose="First vote on each LLM-judged rubric check; grades the simulated learner.",
    ),
    LLMRole.JUDGE_CONFIRM: RoleDefault(
        tier="fast",
        reasoning_effort="medium",
        max_output_tokens=8000,
        purpose="Second, more careful vote before a FAIL is accepted.",
    ),
    LLMRole.JUDGE_TIEBREAK: RoleDefault(
        tier="primary",
        reasoning_effort="low",
        max_output_tokens=6000,
        purpose="Breaks ties when the first two votes disagree.",
    ),
    LLMRole.FACT_CHECKER: RoleDefault(
        tier="fast",
        # Claim extraction reads the whole lesson; at "medium" the model can spend the entire
        # output budget on reasoning (seen live), which errors the check. Low effort + headroom.
        reasoning_effort="low",
        max_output_tokens=24000,
        purpose="ReAct agent that verifies every claim against the knowledge base.",
    ),
    LLMRole.LEARNER: RoleDefault(
        tier="fast",
        reasoning_effort="none",
        max_output_tokens=4000,
        purpose="Simulated beginner who answers held-out questions from the lesson alone.",
    ),
    LLMRole.REFLECTOR: RoleDefault(
        tier="primary",
        reasoning_effort="medium",
        max_output_tokens=10000,
        purpose="Distils failures and feedback into guidelines (self-evolving memory).",
    ),
}


class RoleOverride(BaseModel):
    tier: Tier | None = None
    deployment: str | None = None
    reasoning_effort: Effort | Literal["default"] | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


class ResolvedRole(BaseModel):
    role: LLMRole
    tier: Tier
    deployment: str
    reasoning_effort: str | None
    temperature: float | None
    max_output_tokens: int
    purpose: str


class Price(BaseModel):
    """USD per 1M tokens."""

    input: float
    cached_input: float
    output: float


# List prices (OpenAI, Oct 2026). Azure pay-as-you-go is usually identical; override via
# LLM_PRICING='{"gpt-5.5": {"input": 5, "cached_input": 0.5, "output": 30}}' if yours differ.
DEFAULT_PRICES: dict[str, Price] = {
    "gpt-5.5": Price(input=5.0, cached_input=0.5, output=30.0),
    "gpt-5.4-mini": Price(input=0.75, cached_input=0.075, output=4.5),
    "gpt-4o": Price(input=2.5, cached_input=1.25, output=10.0),
}


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    azure_openai_endpoint: str = ""
    azure_openai_api_key: SecretStr = SecretStr("")
    # A dated API version uses AzureChatOpenAI; "v1" uses the GA v1 endpoint (/openai/v1/).
    azure_openai_api_version: str = "2025-04-01-preview"
    azure_openai_embedding_deployment: str = ""

    llm_primary_deployment: str = "gpt-5.5"
    llm_fast_deployment: str = "gpt-5.4-mini"
    llm_use_responses_api: bool = False
    llm_max_concurrency: int = 4
    llm_timeout_seconds: float = 300.0
    llm_max_retries: int = 4

    llm_roles: dict[LLMRole, RoleOverride] = {}
    llm_pricing: dict[str, Price] = {}

    @property
    def configured(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key.get_secret_value())

    def resolve(self, role: LLMRole) -> ResolvedRole:
        default = ROLE_DEFAULTS[role]
        override = self.llm_roles.get(role, RoleOverride())
        tier: Tier = override.tier or default.tier
        deployment = override.deployment or (
            self.llm_primary_deployment if tier == "primary" else self.llm_fast_deployment
        )
        effort: str | None = default.reasoning_effort
        if override.reasoning_effort is not None:
            effort = None if override.reasoning_effort == "default" else override.reasoning_effort
        return ResolvedRole(
            role=role,
            tier=tier,
            deployment=deployment,
            reasoning_effort=effort,
            temperature=override.temperature,
            max_output_tokens=override.max_output_tokens or default.max_output_tokens,
            purpose=default.purpose,
        )

    def price_for(self, model_name: str) -> Price | None:
        """Longest-prefix match of the served model name (e.g. 'gpt-5.5-2026-04-24')."""
        table = {**DEFAULT_PRICES, **self.llm_pricing}
        name = model_name.lower()
        matches = [key for key in table if name.startswith(key.lower())]
        if not matches:
            return None
        return table[max(matches, key=len)]
