"""Name -> LLMProvider class registry, populated by vocal_coach.llm.providers."""
from __future__ import annotations

from typing import Callable

from vocal_coach.config import LLMConfig
from vocal_coach.llm.base import LLMError, LLMProvider
from vocal_coach.settings import Settings

_REGISTRY: dict[str, type[LLMProvider]] = {}


def register(name: str) -> Callable[[type[LLMProvider]], type[LLMProvider]]:
    def decorator(cls: type[LLMProvider]) -> type[LLMProvider]:
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_provider(name: str, cfg: LLMConfig, settings: Settings) -> LLMProvider:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise LLMError(f"unknown LLM provider {name!r}") from None
    return cls(cfg, settings)


def names() -> list[str]:
    return list(_REGISTRY)
