"""Settings shared by every service.

One root ``.env`` feeds all containers (``env_file`` in docker-compose); per-container values
such as ``ROOT_PATH`` or ``SERVICE_PORT`` are set in each service's ``environment:`` block.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    log_json: bool = True

    service_host: str = "0.0.0.0"
    service_port: int = 8000
    # Prefix under which the gateway exposes this service (e.g. /api/evaluator) so that
    # Swagger UI at /api/evaluator/docs generates correct URLs.
    root_path: str = ""
    cors_origins: list[str] = Field(default_factory=list)

    redis_url: str = "redis://localhost:6379/0"
    # Must exceed the longest blocking stream read (SSE tails block for up to 10 s).
    redis_socket_timeout_seconds: float = 30.0
    events_enabled: bool = True
    event_stream_maxlen: int = 5000
    event_stream_ttl_days: int = 30

    # Internal service discovery (docker-compose DNS names by default).
    knowledge_url: str = "http://knowledge:8003"
    memory_url: str = "http://memory:8004"
    generator_url: str = "http://generator:8001"
    evaluator_url: str = "http://evaluator:8002"
    orchestrator_url: str = "http://orchestrator-api:8000"

    # Default timeouts for service-to-service calls (seconds). LLM-heavy calls override these.
    http_timeout_seconds: float = 30.0
    http_connect_timeout_seconds: float = 5.0
    http_retries: int = 3
