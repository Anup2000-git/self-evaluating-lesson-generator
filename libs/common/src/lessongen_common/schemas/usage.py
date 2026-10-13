"""Token and cost accounting shared by every service that calls an LLM."""

from __future__ import annotations

from pydantic import BaseModel


class ModelUsage(BaseModel):
    llm_calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: ModelUsage) -> None:
        self.llm_calls += other.llm_calls
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_tokens += other.reasoning_tokens
        self.cost_usd = round(self.cost_usd + other.cost_usd, 6)


class Usage(ModelUsage):
    """Totals plus a per-model breakdown (models differ ~6x in price)."""

    by_model: dict[str, ModelUsage] = {}

    def add(self, other: ModelUsage) -> None:  # type: ignore[override]
        super().add(other)
        if isinstance(other, Usage):
            for model, usage in other.by_model.items():
                self.by_model.setdefault(model, ModelUsage()).add(usage)

    def add_call(self, model: str, call: ModelUsage) -> None:
        super().add(call)
        self.by_model.setdefault(model, ModelUsage()).add(call)

    @classmethod
    def merge(cls, *items: Usage | None) -> Usage:
        total = cls()
        for item in items:
            if item is not None:
                total.add(item)
        return total
