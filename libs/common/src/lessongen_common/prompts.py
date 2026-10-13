"""Versioned prompt templates.

Prompts live as Jinja2 files next to the service that owns them. Every rendered prompt
has a short content hash (its version) that is recorded with the output, so a lesson or
verdict can always be traced back to the exact prompt text that produced it.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )


class PromptLibrary:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @lru_cache(maxsize=64)  # noqa: B019 - libraries live for the process lifetime
    def source(self, name: str) -> str:
        return (self.directory / name).read_text(encoding="utf-8")

    def version(self, name: str) -> str:
        return f"{name.split('.')[0]}@{hashlib.sha1(self.source(name).encode()).hexdigest()[:8]}"

    def render(self, name: str, **variables: Any) -> str:
        return _env().from_string(self.source(name)).render(**variables).strip()
