-- One Postgres instance, one logical database per owning service (database-per-service).
-- In production these would typically be separate managed instances.
CREATE DATABASE lessongen_memory;
CREATE DATABASE lessongen_orchestrator;
-- Self-hosted Langfuse (tracing) keeps its metadata here; traces themselves go to ClickHouse.
CREATE DATABASE langfuse;
