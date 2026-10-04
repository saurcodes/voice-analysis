"""Tests for the Anthropic provider: structured-output request shape, stop_reason
handling, exception mapping, content parsing, and list_models. No network;
anthropic.Anthropic is patched with a fake client."""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from vocal_coach.config import LLMConfig
from vocal_coach.llm.base import LLMError
from vocal_coach.llm.providers.anthropic_provider import DEFAULT_MODEL, AnthropicProvider
from vocal_coach.llm.schema import COACHING_SCHEMA
from vocal_coach.settings import Settings

SYSTEM_PROMPT = "You are a vocal coach."
USER_PAYLOAD = {"b": 1, "a": 2}
MODEL = "test-model"

VALID_ANSWER = {
    "what_improved": ["pace steadied"],
    "what_is_lacking": ["weak endings"],
    "next_steps": ["drill falling finishes"],
    "marked_up_example": "hello there",
}


def _cfg(**overrides) -> LLMConfig:
    defaults = dict(
        base_url="http://unused.invalid", model=MODEL, seed=42, timeout_s=5.0, max_output_tokens=512
    )
    defaults.update(overrides)
    return LLMConfig(**defaults)


def _settings(api_key: str | None = "k") -> Settings:
    return Settings(_env_file=None, anthropic_api_key=api_key)


class FakeMessages:
    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exception is not None:
            raise self._exception
        return self._response


class FakeModels:
    def __init__(self, models=None, exception=None):
        self._models = models or []
        self._exception = exception

    def list(self):
        if self._exception is not None:
            raise self._exception
        return self._models


class FakeAnthropicClient:
    """Stands in for anthropic.Anthropic(...): records constructor kwargs."""

    last_instance: "FakeAnthropicClient | None" = None

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.messages = FakeMessages()
        self.models = FakeModels()
        FakeAnthropicClient.last_instance = self


def _message(stop_reason: str, text: str | None):
    content = [] if text is None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(stop_reason=stop_reason, content=content)


def test_constructor_raises_when_api_key_missing():
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY is not set"):
        AnthropicProvider(_cfg(), _settings(api_key=None))


def test_constructor_builds_client_with_key_timeout_and_max_retries(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    AnthropicProvider(_cfg(timeout_s=7.0), _settings(api_key="secret"))
    client = FakeAnthropicClient.last_instance
    assert client.init_kwargs["api_key"] == "secret"
    assert client.init_kwargs["timeout"] == 7.0
    assert client.init_kwargs["max_retries"] == 1


def test_request_shape_has_output_config_system_and_no_temperature_or_tool_choice(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.messages = FakeMessages(
        response=_message("end_turn", json.dumps(VALID_ANSWER))
    )

    result = provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    assert result == VALID_ANSWER
    kwargs = provider._client.messages.calls[0]
    assert kwargs["model"] == MODEL
    assert kwargs["max_tokens"] == 512
    assert kwargs["system"] == SYSTEM_PROMPT
    assert kwargs["messages"] == [
        {"role": "user", "content": json.dumps(USER_PAYLOAD, sort_keys=True)}
    ]
    assert kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": COACHING_SCHEMA}
    }
    assert "temperature" not in kwargs
    assert "tool_choice" not in kwargs
    assert "tools" not in kwargs
    assert "thinking" not in kwargs


def test_empty_model_falls_back_to_default_model(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.messages = FakeMessages(
        response=_message("end_turn", json.dumps(VALID_ANSWER))
    )

    provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model="")

    assert provider._client.messages.calls[0]["model"] == DEFAULT_MODEL


def test_refusal_stop_reason_raises_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.messages = FakeMessages(response=_message("refusal", None))

    with pytest.raises(LLMError, match="anthropic declined the request"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_max_tokens_stop_reason_raises_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.messages = FakeMessages(
        response=_message("max_tokens", json.dumps(VALID_ANSWER))
    )

    with pytest.raises(LLMError, match="anthropic response truncated"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_no_text_block_raises_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.messages = FakeMessages(response=_message("end_turn", None))

    with pytest.raises(LLMError, match="model returned no text"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_non_json_text_raises_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.messages = FakeMessages(response=_message("end_turn", "not json at all"))

    with pytest.raises(LLMError, match="model returned non-JSON content"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_non_object_json_text_raises_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.messages = FakeMessages(
        response=_message("end_turn", json.dumps(["not", "an", "object"]))
    )

    with pytest.raises(LLMError, match="model returned non-JSON content"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_api_status_error_maps_to_llm_error_with_status_code(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    response = httpx2.Response(500, request=httpx2.Request("POST", "https://example.invalid"))
    exc = anthropic.APIStatusError("x", response=response, body=None)
    provider._client.messages = FakeMessages(exception=exc)

    with pytest.raises(LLMError, match="anthropic error 500"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_api_timeout_error_maps_to_llm_error_with_connection_error_message(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    exc = anthropic.APITimeoutError(request=httpx2.Request("POST", "https://example.invalid"))
    provider._client.messages = FakeMessages(exception=exc)

    with pytest.raises(LLMError, match="connection error"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_other_api_error_maps_to_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    exc = anthropic.APIWebhookValidationError(
        "x", request=httpx2.Request("POST", "https://example.invalid"), body=None
    )
    provider._client.messages = FakeMessages(exception=exc)

    with pytest.raises(LLMError, match="anthropic error: APIWebhookValidationError"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_list_models_sorts_ids(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.models = FakeModels(
        models=[SimpleNamespace(id="zeta"), SimpleNamespace(id="alpha"), SimpleNamespace(id="mid")]
    )

    assert provider.list_models() == ["alpha", "mid", "zeta"]


def test_list_models_api_status_error_maps_to_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    response = httpx2.Response(503, request=httpx2.Request("GET", "https://example.invalid"))
    provider._client.models = FakeModels(exception=anthropic.APIStatusError("x", response=response, body=None))

    with pytest.raises(LLMError, match="anthropic error 503"):
        provider.list_models()


def test_list_models_connection_error_maps_to_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    exc = anthropic.APITimeoutError(request=httpx2.Request("GET", "https://example.invalid"))
    provider._client.models = FakeModels(exception=exc)

    with pytest.raises(LLMError, match="connection error"):
        provider.list_models()


def test_list_models_unexpected_exception_shape_maps_to_llm_error(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)
    provider = AnthropicProvider(_cfg(), _settings())
    provider._client.models = FakeModels(exception=AttributeError("boom"))

    with pytest.raises(LLMError, match="anthropic models listing failed"):
        provider.list_models()
