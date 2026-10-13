"""Builds (and caches) one chat model per role from ``LLMSettings``.

Services receive an ``LLMProvider`` at startup; tests pass ``overrides`` with scripted fake
models, so no test ever needs Azure credentials.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from lessongen_common.llm.config import LLMRole, LLMSettings, ResolvedRole
from lessongen_common.llm.usage import UsageCallback


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMProvider:
    def __init__(
        self,
        settings: LLMSettings | None = None,
        overrides: dict[LLMRole, BaseChatModel] | None = None,
    ) -> None:
        self.settings = settings or LLMSettings()
        self._overrides = dict(overrides or {})
        self._cache: dict[LLMRole, BaseChatModel] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None

    def resolve(self, role: LLMRole) -> ResolvedRole:
        return self.settings.resolve(role)

    def get(self, role: LLMRole) -> BaseChatModel:
        if role in self._overrides:
            return self._overrides[role]
        if role not in self._cache:
            self._cache[role] = self._build(self.resolve(role))
        return self._cache[role]

    def model_label(self, role: LLMRole) -> str:
        if role in self._overrides:
            return getattr(self._overrides[role], "model_name", "fake")
        return self.resolve(role).deployment

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Bound concurrent LLM calls per process (protects the Azure TPM quota)."""
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not loop:
            self._semaphore = asyncio.Semaphore(max(1, self.settings.llm_max_concurrency))
            self._semaphore_loop = loop
        async with self._semaphore:
            yield

    def describe(self) -> list[dict[str, Any]]:
        """Role -> model mapping for the System page (never includes secrets)."""
        rows = []
        for role in LLMRole:
            resolved = self.resolve(role)
            rows.append(
                {
                    "role": role.value,
                    "tier": resolved.tier,
                    "deployment": self.model_label(role),
                    "reasoning_effort": resolved.reasoning_effort,
                    "max_output_tokens": resolved.max_output_tokens,
                    "purpose": resolved.purpose,
                }
            )
        return rows

    def _build(self, resolved: ResolvedRole) -> BaseChatModel:
        s = self.settings
        if not s.configured:
            raise LLMNotConfiguredError(
                "Azure OpenAI is not configured: set AZURE_OPENAI_ENDPOINT and "
                "AZURE_OPENAI_API_KEY in .env"
            )
        kwargs: dict[str, Any] = {
            "api_key": s.azure_openai_api_key,
            "timeout": s.llm_timeout_seconds,
            "max_retries": s.llm_max_retries,
            "max_tokens": resolved.max_output_tokens,
            "callbacks": [UsageCallback(resolved.deployment, s)],
        }
        if resolved.reasoning_effort:
            kwargs["reasoning_effort"] = resolved.reasoning_effort
        if resolved.temperature is not None:
            kwargs["temperature"] = resolved.temperature
        if s.llm_use_responses_api:
            kwargs["use_responses_api"] = True

        if s.azure_openai_api_version.strip().lower() == "v1":
            from langchain_openai import ChatOpenAI

            base_url = s.azure_openai_endpoint.rstrip("/") + "/openai/v1/"
            return ChatOpenAI(model=resolved.deployment, base_url=base_url, **kwargs)

        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=s.azure_openai_endpoint,
            azure_deployment=resolved.deployment,
            api_version=s.azure_openai_api_version,
            model=resolved.deployment,
            **kwargs,
        )
