"""Cross-provider contract test: every registered LLM provider must produce a
validated CoachingOutput with zero warnings for a numerically faithful answer,
driven through the same run_coaching orchestration. No network calls: the
anthropic client is patched and the openai_compatible HTTP call is mocked."""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import pytest

import vocal_coach.llm.providers  # noqa: F401 - import registers every built-in provider
from vocal_coach.config import LLMConfig
from vocal_coach.llm.coach import run_coaching
from vocal_coach.llm.registry import get_provider, names
from vocal_coach.llm.schema import CoachingOutput
from vocal_coach.settings import Settings

PAYLOAD = {
    "metrics": {"pitch": {"f0_range_st": 4.3}},
    "transcript_text": "so we will win today, right",
    "transcript_derived": None,
    "comparison": None,
    "speaker_context": None,
}

ANSWER = {
    "what_improved": ["pitch range opened to 4.3 semitones"],
    "what_is_lacking": [],
    "next_steps": [],
    "marked_up_example": "so we will win today",
}

OPENAI_BASE_URL = "http://llm.test/v1"
OPENAI_CHAT_URL = f"{OPENAI_BASE_URL}/chat/completions"

PROVIDER_NAMES = ["anthropic", "openai_compatible"]


def test_registry_has_both_builtin_providers():
    assert set(PROVIDER_NAMES) <= set(names())


def _anthropic_provider(monkeypatch):
    class FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=json.dumps(ANSWER))],
            )

    class FakeAnthropicClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    cfg = LLMConfig(
        base_url="http://unused.invalid", model="m", seed=42, timeout_s=5.0, max_output_tokens=512
    )
    settings = Settings(_env_file=None, anthropic_api_key="k")
    return get_provider("anthropic", cfg, settings)


def _openai_compatible_provider(httpx_mock):
    httpx_mock.add_response(
        status_code=200,
        url=OPENAI_CHAT_URL,
        method="POST",
        json={"choices": [{"message": {"content": json.dumps(ANSWER)}}]},
    )
    cfg = LLMConfig(
        base_url=OPENAI_BASE_URL, model="m", seed=42, timeout_s=5.0, max_output_tokens=512
    )
    settings = Settings(_env_file=None, openai_compat_api_key=None)
    return get_provider("openai_compatible", cfg, settings)


@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
def test_provider_produces_valid_coaching_with_no_warnings(provider_name, monkeypatch, httpx_mock):
    if provider_name == "anthropic":
        provider = _anthropic_provider(monkeypatch)
    else:
        provider = _openai_compatible_provider(httpx_mock)

    result = run_coaching(provider, PAYLOAD, model="m")

    assert result.warnings == []
    CoachingOutput.model_validate(result.coaching)

    if provider_name == "openai_compatible":
        sent = json.loads(httpx_mock.get_requests()[0].content)
        assert sent["temperature"] == 0
