"""Tests for the OpenAI-compatible provider: json_schema path, json_object
fallback on 4xx, error mapping for 5xx/timeouts, content parsing, and
list_models. No network; every request is mocked via pytest-httpx."""
from __future__ import annotations

import json

import httpx
import pytest

from vocal_coach.config import LLMConfig
from vocal_coach.llm.base import LLMError
from vocal_coach.llm.providers.openai_compatible import OpenAICompatibleProvider
from vocal_coach.llm.schema import COACHING_SCHEMA
from vocal_coach.settings import Settings

BASE_URL = "http://llm.test/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"
MODELS_URL = f"{BASE_URL}/models"

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
    defaults = dict(base_url=BASE_URL, model=MODEL, seed=42, timeout_s=5.0, max_output_tokens=512)
    defaults.update(overrides)
    return LLMConfig(**defaults)


def _settings(api_key: str | None = None) -> Settings:
    return Settings(_env_file=None, openai_compat_api_key=api_key)


def _chat_response(content, *, status_code: int = 200) -> dict:
    return dict(
        status_code=status_code,
        url=CHAT_URL,
        method="POST",
        json={"choices": [{"message": {"content": content}}]},
    )


def test_json_schema_success_sends_strict_schema_and_parses_answer(httpx_mock):
    httpx_mock.add_response(**_chat_response(json.dumps(VALID_ANSWER)))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    result = provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    assert result == VALID_ANSWER

    reqs = httpx_mock.get_requests()
    assert len(reqs) == 1
    sent = json.loads(reqs[0].content)
    assert sent["model"] == MODEL
    assert sent["temperature"] == 0
    assert sent["seed"] == 42
    assert sent["max_tokens"] == 512
    assert sent["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(USER_PAYLOAD, sort_keys=True)},
    ]
    assert sent["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "coaching_output", "strict": True, "schema": COACHING_SCHEMA},
    }


def test_400_falls_back_to_json_object_with_schema_in_system_prompt(httpx_mock):
    httpx_mock.add_response(**_chat_response("", status_code=400))
    httpx_mock.add_response(**_chat_response(json.dumps(VALID_ANSWER)))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    result = provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    assert result == VALID_ANSWER

    reqs = httpx_mock.get_requests()
    assert len(reqs) == 2
    second = json.loads(reqs[1].content)
    assert second["response_format"] == {"type": "json_object"}
    expected_system = (
        SYSTEM_PROMPT + "\n\nThe JSON must match this schema exactly:\n" + json.dumps(COACHING_SCHEMA)
    )
    assert second["messages"][0] == {"role": "system", "content": expected_system}
    assert second["messages"][1] == {"role": "user", "content": json.dumps(USER_PAYLOAD, sort_keys=True)}


def test_400_then_400_raises_llm_error(httpx_mock):
    httpx_mock.add_response(**_chat_response("", status_code=400))
    httpx_mock.add_response(**_chat_response("", status_code=400))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="openai-compatible error 400"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    assert len(httpx_mock.get_requests()) == 2


def test_500_raises_llm_error_with_exactly_one_request(httpx_mock):
    httpx_mock.add_response(**_chat_response("", status_code=500))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="openai-compatible error 500"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    assert len(httpx_mock.get_requests()) == 1


def test_non_json_content_raises_llm_error(httpx_mock):
    httpx_mock.add_response(**_chat_response("not json at all"))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="model returned non-JSON content"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_content_json_list_raises_llm_error(httpx_mock):
    httpx_mock.add_response(**_chat_response(json.dumps(["not", "an", "object"])))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="model returned non-JSON content"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_list_models_parses_and_sorts_ids(httpx_mock):
    httpx_mock.add_response(
        url=MODELS_URL,
        method="GET",
        json={"data": [{"id": "zeta"}, {"id": "alpha"}, {"id": "mid"}]},
    )

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    assert provider.list_models() == ["alpha", "mid", "zeta"]


def test_list_models_error_shape_raises_llm_error(httpx_mock):
    httpx_mock.add_response(url=MODELS_URL, method="GET", json={"oops": True})

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError):
        provider.list_models()


def test_list_models_http_error_raises_llm_error(httpx_mock):
    httpx_mock.add_response(url=MODELS_URL, method="GET", status_code=500)

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="openai-compatible error 500"):
        provider.list_models()


def test_auth_header_present_only_when_key_configured(httpx_mock):
    httpx_mock.add_response(**_chat_response(json.dumps(VALID_ANSWER)))

    provider = OpenAICompatibleProvider(_cfg(), _settings(api_key="secret-key"))
    provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    req = httpx_mock.get_requests()[0]
    assert req.headers["authorization"] == "Bearer secret-key"


def test_auth_header_absent_when_no_key_configured(httpx_mock):
    httpx_mock.add_response(**_chat_response(json.dumps(VALID_ANSWER)))

    provider = OpenAICompatibleProvider(_cfg(), _settings(api_key=None))
    provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    req = httpx_mock.get_requests()[0]
    assert "authorization" not in req.headers


def test_timeout_raises_llm_error_with_connection_error_message(httpx_mock):
    httpx_mock.add_exception(httpx.ReadTimeout("t"), url=CHAT_URL, method="POST")

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="connection error"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_malformed_2xx_body_raises_llm_error_instead_of_json_decode_error(httpx_mock):
    httpx_mock.add_response(status_code=200, url=CHAT_URL, method="POST", text="{not valid json")

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="openai-compatible returned a malformed response"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_list_models_malformed_body_raises_llm_error_instead_of_json_decode_error(httpx_mock):
    httpx_mock.add_response(status_code=200, url=MODELS_URL, method="GET", text="{not valid json")

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="openai-compatible returned a malformed response"):
        provider.list_models()


def test_timeout_on_fallback_request_raises_llm_error(httpx_mock):
    httpx_mock.add_response(**_chat_response("", status_code=400))
    httpx_mock.add_exception(httpx.ReadTimeout("t"), url=CHAT_URL, method="POST")

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="connection error"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    assert len(httpx_mock.get_requests()) == 2


def test_fenced_json_content_is_parsed(httpx_mock):
    fenced = "```json\n" + json.dumps(VALID_ANSWER) + "\n```"
    httpx_mock.add_response(**_chat_response(fenced))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    assert provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL) == VALID_ANSWER


def test_bare_fence_content_is_parsed(httpx_mock):
    fenced = "```\n" + json.dumps(VALID_ANSWER) + "\n```\n"
    httpx_mock.add_response(**_chat_response(fenced))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    assert provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL) == VALID_ANSWER


def test_think_prefix_is_stripped(httpx_mock):
    content = "<think>\nThe user wants {json}.\nOk.\n</think>\n" + json.dumps(VALID_ANSWER)
    httpx_mock.add_response(**_chat_response(content))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    assert provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL) == VALID_ANSWER


def test_brace_slice_recovers_json_wrapped_in_prose(httpx_mock):
    content = "Here is your coaching: " + json.dumps(VALID_ANSWER) + " Hope this helps."
    httpx_mock.add_response(**_chat_response(content))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    assert provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL) == VALID_ANSWER


def test_finish_reason_length_raises_truncated(httpx_mock):
    httpx_mock.add_response(
        status_code=200, url=CHAT_URL, method="POST",
        json={"choices": [{"message": {"content": '{"what_improved": ['}, "finish_reason": "length"}]},
    )

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match="model response truncated"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)


def test_422_falls_back_to_json_object(httpx_mock):
    httpx_mock.add_response(**_chat_response("", status_code=422))
    httpx_mock.add_response(**_chat_response(json.dumps(VALID_ANSWER)))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    assert provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL) == VALID_ANSWER
    assert json.loads(httpx_mock.get_requests()[1].content)["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_non_schema_4xx_does_not_fall_back(httpx_mock, status):
    httpx_mock.add_response(**_chat_response("", status_code=status))

    provider = OpenAICompatibleProvider(_cfg(), _settings())
    with pytest.raises(LLMError, match=f"openai-compatible error {status}"):
        provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    assert len(httpx_mock.get_requests()) == 1


def test_chat_timeout_is_10s_connect_and_configured_read(httpx_mock):
    httpx_mock.add_response(**_chat_response(json.dumps(VALID_ANSWER)))

    provider = OpenAICompatibleProvider(_cfg(timeout_s=77.0), _settings())
    provider.generate_coaching(SYSTEM_PROMPT, USER_PAYLOAD, COACHING_SCHEMA, model=MODEL)

    timeout = httpx_mock.get_requests()[0].extensions["timeout"]
    assert timeout["connect"] == 10.0
    assert timeout["read"] == 77.0


def test_list_models_timeout_is_10s(httpx_mock):
    httpx_mock.add_response(url=MODELS_URL, method="GET", json={"data": [{"id": "a"}]})

    provider = OpenAICompatibleProvider(_cfg(timeout_s=300.0), _settings())
    provider.list_models()

    timeout = httpx_mock.get_requests()[0].extensions["timeout"]
    assert timeout == {"connect": 10.0, "read": 10.0, "write": 10.0, "pool": 10.0}
