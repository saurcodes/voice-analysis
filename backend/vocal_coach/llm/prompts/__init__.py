"""Loads the bundled coach system prompt."""
from __future__ import annotations

import functools
from importlib import resources


@functools.lru_cache(maxsize=1)
def load_system_prompt() -> str:
    return resources.files(__package__).joinpath("coach.md").read_text(encoding="utf-8")
