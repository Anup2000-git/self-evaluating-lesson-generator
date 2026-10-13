from __future__ import annotations

from lessongen_common.settings import ServiceSettings


class GeneratorSettings(ServiceSettings):
    service_port: int = 8001
    writer_max_steps: int = 10
    writer_max_rejections: int = 3
    planner_notes_per_query: int = 2
    planner_max_attempts: int = 2
    knowledge_timeout_seconds: float = 15.0
    rubric_cache_seconds: float = 30.0
