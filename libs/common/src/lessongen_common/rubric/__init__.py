"""Seed rubric shipped with the code. Live, versioned rubrics are stored by the memory service."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml

from lessongen_common.schemas.rubric import Rubric

SEED_RUBRIC_FILE = "rubric.v1.yaml"


def parse_rubric(text: str) -> Rubric:
    return Rubric.model_validate(yaml.safe_load(text))


@lru_cache(maxsize=1)
def load_seed_rubric() -> Rubric:
    text = resources.files(__package__).joinpath(SEED_RUBRIC_FILE).read_text(encoding="utf-8")
    return parse_rubric(text)
