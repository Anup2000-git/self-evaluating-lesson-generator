# syntax=docker/dockerfile:1.7
# One Dockerfile for every Python microservice (uv workspace monorepo).
#   docker build -f docker/python-service.Dockerfile --build-arg PACKAGE=lessongen-evaluator .
# The runtime image contains only a self-contained virtualenv (no sources, no build tools)
# and runs as an unprivileged user. Each service's command is set in docker-compose.yml.

ARG PYTHON_VERSION=3.13

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
ARG PACKAGE

# 1) Third-party dependencies only - cached until uv.lock or a pyproject changes.
COPY pyproject.toml uv.lock ./
COPY libs/common/pyproject.toml libs/common/pyproject.toml
COPY services/knowledge/pyproject.toml services/knowledge/pyproject.toml
COPY services/memory/pyproject.toml services/memory/pyproject.toml
COPY services/generator/pyproject.toml services/generator/pyproject.toml
COPY services/evaluator/pyproject.toml services/evaluator/pyproject.toml
COPY services/orchestrator/pyproject.toml services/orchestrator/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package "${PACKAGE}"

# 2) Our code, installed non-editable so the venv is self-contained.
COPY libs/common libs/common
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package "${PACKAGE}"

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system app && useradd --system --gid app --uid 10001 --create-home --home-dir /app app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
USER app
