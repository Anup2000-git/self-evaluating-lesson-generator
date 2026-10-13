-- One Postgres instance, one logical database per owning service (database-per-service).
-- In production these would typically be separate managed instances.
CREATE DATABASE lessongen_memory;
CREATE DATABASE lessongen_orchestrator;
