"""LLMProvider ABC: the contract every coaching provider implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from vocal_coach.config import LLMConfig
from vocal_coach.settings import Settings


class LLMError(RuntimeError):
    """Any provider failure: network, auth, HTTP status, or a non-JSON answer."""


class LLMProvider(ABC):
    name: str

    def __init__(self, cfg: LLMConfig, settings: Settings) -> None:
        self.cfg = cfg
        self.settings = settings

    @abstractmethod
    def generate_coaching(
        self, system_prompt: str, user_payload: dict, schema: dict, *, model: str
    ) -> dict:
        """Return the parsed JSON object the model produced (not yet validated).

        Raises LLMError on any failure (network, auth, HTTP status, non-JSON answer).
        """

    def list_models(self) -> list[str]:
        """Return the provider's available model names, or [] if not supported.

        Raises LLMError on failure.
        """
        return []
