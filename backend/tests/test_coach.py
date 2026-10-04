import copy

from vocal_coach.llm.base import LLMError
from vocal_coach.llm.coach import INVALID_OUTPUT, CoachResult, run_coaching

from .fake_llm import FakeProvider

VALID = {
    "what_improved": ["steadier pace"],
    "what_is_lacking": ["pitch range stayed flat"],
    "next_steps": ["open up the pitch range on stressed words"],
    "marked_up_example": "so WE will win today",
}

PAYLOAD = {
    "metrics": {"pitch": {"f0_range_st": 17.26}},
    "transcript_text": "So we will win today, right?",
    "transcript_derived": None,
    "comparison": None,
    "speaker_context": None,
}


def test_invalid_then_valid_retries_once_with_previous_error_and_stores_result():
    invalid = {"what_improved": [], "what_is_lacking": [], "next_steps": []}  # missing marked_up_example
    provider = FakeProvider([invalid, VALID])

    result = run_coaching(provider, PAYLOAD, model="fake-1")

    assert result.coaching == VALID
    assert result.warnings == []
    assert len(provider.calls) == 2
    assert "previous_error" not in provider.calls[0]
    assert "previous_error" in provider.calls[1]
    assert isinstance(provider.calls[1]["previous_error"], str) and provider.calls[1]["previous_error"]


def test_two_invalid_answers_gives_none_and_invalid_output_warning():
    invalid = {"what_improved": [], "what_is_lacking": [], "next_steps": []}
    provider = FakeProvider([invalid, invalid])

    result = run_coaching(provider, PAYLOAD, model="fake-1")

    assert result.coaching is None
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith(INVALID_OUTPUT)
    assert len(provider.calls) == 2


def test_llm_error_gives_none_and_coaching_failed_warning_with_one_call():
    provider = FakeProvider([LLMError("boom")])

    result = run_coaching(provider, PAYLOAD, model="fake-1")

    assert result == CoachResult(None, ["coaching failed: boom"])
    assert len(provider.calls) == 1


def test_valid_output_with_invented_number_and_bad_example_keeps_coaching_with_both_warnings():
    out = {
        "what_improved": [],
        "what_is_lacking": ["range stayed at 99.9 st"],
        "next_steps": [],
        "marked_up_example": "we lose today",
    }
    provider = FakeProvider([out])

    result = run_coaching(provider, PAYLOAD, model="fake-1")

    assert result.coaching == out
    assert any("99.9" in w for w in result.warnings)
    assert "marked_up_example does not match the transcript" in result.warnings
    assert len(result.warnings) == 2


def test_non_dict_answer_counts_as_validation_failure_and_retries():
    provider = FakeProvider([[1, 2, 3], VALID])

    result = run_coaching(provider, PAYLOAD, model="fake-1")

    assert result.coaching == VALID
    assert len(provider.calls) == 2
    assert "previous_error" in provider.calls[1]


def test_unexpected_exception_gives_none_and_type_name_warning():
    provider = FakeProvider([RuntimeError("kaboom")])

    result = run_coaching(provider, PAYLOAD, model="fake-1")

    assert result == CoachResult(None, ["coaching failed: RuntimeError"])
    assert len(provider.calls) == 1


def test_original_payload_not_mutated_by_retry():
    invalid = {"what_improved": [], "what_is_lacking": [], "next_steps": []}
    provider = FakeProvider([invalid, VALID])
    payload_copy = copy.deepcopy(PAYLOAD)

    run_coaching(provider, payload_copy, model="fake-1")

    assert payload_copy == PAYLOAD
    assert "previous_error" not in payload_copy


def test_retry_skipped_when_first_call_exceeds_deadline(monkeypatch):
    import vocal_coach.llm.coach as coach_mod

    ticks = iter([0.0, 50.0])
    monkeypatch.setattr(coach_mod.time, "monotonic", lambda: next(ticks))
    invalid = {"what_improved": [], "what_is_lacking": [], "next_steps": []}
    provider = FakeProvider([invalid, VALID])

    result = run_coaching(provider, PAYLOAD, model="fake-1", deadline_s=30.0)

    assert result.coaching is None
    assert len(result.warnings) == 1 and result.warnings[0].startswith(INVALID_OUTPUT)
    assert len(provider.calls) == 1


def test_retry_runs_when_within_deadline(monkeypatch):
    import vocal_coach.llm.coach as coach_mod

    ticks = iter([0.0, 5.0])
    monkeypatch.setattr(coach_mod.time, "monotonic", lambda: next(ticks))
    invalid = {"what_improved": [], "what_is_lacking": [], "next_steps": []}
    provider = FakeProvider([invalid, VALID])

    result = run_coaching(provider, PAYLOAD, model="fake-1", deadline_s=30.0)

    assert result.coaching == VALID
    assert len(provider.calls) == 2


def test_previous_error_is_truncated_to_500_chars():
    invalid = {"what_improved": list(range(200)), "what_is_lacking": [], "next_steps": []}
    provider = FakeProvider([invalid, VALID])

    run_coaching(provider, PAYLOAD, model="fake-1")

    previous_error = provider.calls[1]["previous_error"]
    assert 0 < len(previous_error) <= 500
