"""Exception types shared across services."""

from __future__ import annotations

from typing import Any


class LessongenError(Exception):
    """Base class for expected, well-described failures."""


class ServiceError(LessongenError):
    """A call to another microservice failed (non-2xx response or transport error)."""

    def __init__(
        self, service: str, status: int | None, detail: str, body: Any | None = None
    ) -> None:
        self.service = service
        self.status = status
        self.detail = detail
        self.body = body
        super().__init__(f"{service} -> {status}: {detail}")


class StructuredOutputError(LessongenError):
    """The model did not return output matching the requested schema after retries."""


class AgentError(LessongenError):
    """A ReAct agent could not produce a valid submission."""


class BudgetExceededError(LessongenError):
    """The run spent more than its configured budget."""


class NotFoundError(LessongenError):
    """A requested resource does not exist."""
