from __future__ import annotations

from lessongen_common.settings import ServiceSettings


class MemorySettings(ServiceSettings):
    service_port: int = 8004
    database_url: str = "postgresql+asyncpg://lessongen:lessongen@postgres:5432/lessongen_memory"
    db_pool_size: int = 5
    # How much memory is injected into a new run.
    context_guideline_limit: int = 10
    context_failure_window_runs: int = 10
    context_failure_min_rate: float = 0.3
    # Self-evolving guardrails.
    max_active_guidelines_per_topic: int = 12
    escalation_window_runs: int = 5
    escalation_min_failures: int = 3
    retire_after_misses: int = 3
