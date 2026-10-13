from __future__ import annotations

from lessongen_common.settings import ServiceSettings


class EvaluatorSettings(ServiceSettings):
    service_port: int = 8002
    # A FAIL from the first judge is confirmed by a second vote; disagreement -> third vote.
    judge_confirm_fails: bool = True
    # rapidfuzz partial_ratio needed for a judge's quote to count as "found in the lesson".
    evidence_match_threshold: int = 88
    fact_check_max_steps: int = 8
    max_claims: int = 30
    rubric_cache_seconds: float = 30.0
    knowledge_timeout_seconds: float = 15.0
