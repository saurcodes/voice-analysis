"""Shared FakeProvider test double for coaching orchestration tests (Tasks 3, 6)."""
from __future__ import annotations

from vocal_coach.llm.base import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, answers: list[dict | Exception], models: list[str] = ("fake-1",)) -> None:
        self.cfg = None
        self.settings = None
        self.calls: list[dict] = []
        self.models = list(models)
        self._answers = list(answers)

    def generate_coaching(self, system_prompt, user_payload, schema, *, model):
        self.calls.append(user_payload)
        if not self._answers:
            raise AssertionError("FakeProvider has no more answers")
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def list_models(self):
        return self.models
