import pytest
from vocal_coach.config import LLMConfig
from vocal_coach.llm import registry
from vocal_coach.llm.base import LLMError, LLMProvider
from vocal_coach.llm.registry import get_provider, names, register
from vocal_coach.llm.schema import COACHING_SCHEMA, CoachingOutput
from vocal_coach.settings import Settings


def test_register_and_get_provider(monkeypatch):
    # register() mutates the module-level _REGISTRY in place; swap in a working copy
    # for the duration of the test so the fake entry never leaks into other tests
    # (a contract test elsewhere asserts the real provider names()).
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))

    @register("fake_for_test")
    class Fake(LLMProvider):
        name = "fake_for_test"
        def generate_coaching(self, system_prompt, user_payload, schema, *, model):
            return {}
    settings = Settings(_env_file=None)
    p = get_provider("fake_for_test", LLMConfig(), settings)
    assert isinstance(p, Fake) and "fake_for_test" in names()


def test_unknown_provider_is_llm_error():
    with pytest.raises(LLMError, match="unknown LLM provider"):
        get_provider("nope", LLMConfig(), Settings(_env_file=None))


def test_schema_matches_model():
    assert COACHING_SCHEMA["additionalProperties"] is False
    assert set(COACHING_SCHEMA["required"]) == {"what_improved", "what_is_lacking", "next_steps", "marked_up_example"}
    with pytest.raises(Exception):
        CoachingOutput.model_validate({"what_improved": [], "what_is_lacking": [], "next_steps": [], "marked_up_example": "x", "extra": 1})


def test_coaching_schema_required_matches_pydantic_model():
    # Guards against the hand-written wire schema drifting from CoachingOutput's fields.
    assert set(CoachingOutput.model_json_schema()["required"]) == set(COACHING_SCHEMA["required"])
