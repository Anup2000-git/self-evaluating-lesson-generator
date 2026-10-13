from __future__ import annotations

from lessongen_common.settings import ServiceSettings


class OrchestratorSettings(ServiceSettings):
    service_port: int = 8000

    # Pipeline policy (the assessment asks for 1-2 retries so the loop always terminates).
    max_retries: int = 2
    run_budget_usd: float = 5.0
    helper_language: str = "Hindi"
    # <= this many failed checks -> targeted patch; more -> rewrite from the plan with feedback.
    patch_max_failed_checks: int = 6
    # If only *errored* checks failed (e.g. an LLM timeout), re-evaluate instead of rewriting.
    evaluation_error_retries: int = 1
    recursion_limit: int = 40

    # Durable graph state (resume after a worker crash). psycopg URL, not SQLAlchemy.
    checkpoint_database_url: str = (
        "postgresql://lessongen:lessongen@postgres:5432/lessongen_orchestrator"
    )
    use_checkpointer: bool = True

    # Job queue (Redis Streams consumer group).
    job_stream: str = "jobs:runs"
    job_group: str = "orchestrator-workers"
    worker_concurrency: int = 2
    # A running worker refreshes its lock every ttl/3; other workers reclaim a pending job only
    # once its lock has expired, so a low idle threshold is safe and makes recovery quick.
    job_lock_ttl_seconds: int = 30
    job_reclaim_idle_ms: int = 30_000
    sse_block_ms: int = 10_000

    # Downstream timeouts (LLM-heavy calls take minutes with reasoning models).
    generator_timeout_seconds: float = 900.0
    evaluator_timeout_seconds: float = 900.0
    consolidation_timeout_seconds: float = 300.0
