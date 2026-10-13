"""Structured JSON logging (structlog) with run/request correlation ids on every line."""

from __future__ import annotations

import logging
import sys

import structlog

from lessongen_common.context import get_context


def _add_run_context(_logger: object, _name: str, event_dict: dict) -> dict:
    ctx = get_context()
    if ctx.request_id and "request_id" not in event_dict:
        event_dict["request_id"] = ctx.request_id
    if ctx.run_id and "run_id" not in event_dict:
        event_dict["run_id"] = ctx.run_id
    if ctx.attempt is not None and "attempt" not in event_dict:
        event_dict["attempt"] = ctx.attempt
    if ctx.node and "node" not in event_dict:
        event_dict["node"] = ctx.node
    return event_dict


def configure_logging(service: str, level: str = "INFO", json: bool = True) -> None:
    """Route both structlog and stdlib (uvicorn, httpx, langchain) logs through one pipeline."""

    def _add_service(_logger: object, _name: str, event_dict: dict) -> dict:
        event_dict.setdefault("service", service)
        return event_dict

    shared: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service,
        _add_run_context,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers[:] = []
        logger.propagate = True
    # Access logs are replaced by our request middleware's single structured line.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
