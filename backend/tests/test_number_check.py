from vocal_coach.llm.number_check import (
    allowed_forms,
    check_numbers,
    extract_numbers,
    numeric_leaves,
)


def test_flags_rerounded_and_invented_numbers():
    payload = {"metrics": {"pitch": {"f0_range_st": 17.26}}, "transcript_derived": None, "comparison": None}
    out = {
        "what_improved": [],
        "what_is_lacking": ["range 17.3 st", "range 17.5 st"],
        "next_steps": [],
        "marked_up_example": "pause // here",
    }
    warnings = check_numbers(out, payload)
    assert any("17.5" in w for w in warnings) and not any("17.3" in w for w in warnings)


def test_accepts_integer_forms_and_ignores_marks():
    payload = {"metrics": {"phrasing": {"pause_count": 4, "pauses_per_min": 12.0}}, "transcript_derived": None, "comparison": None}
    out = {
        "what_improved": ["4 pauses", "12 per min", "12.0 per min"],
        "what_is_lacking": [],
        "next_steps": [],
        "marked_up_example": "F0 // 16k",
    }
    assert check_numbers(out, payload) == []


def test_numeric_leaves_skips_bools_and_strings():
    obj = {"a": True, "b": False, "c": "9", "d": [1, 2.5, {"e": 3}], "f": None}
    assert sorted(numeric_leaves(obj)) == [1.0, 2.5, 3.0]


def test_allowed_forms_has_three_precisions_and_stripped_variants():
    forms = allowed_forms([12.0])
    assert {"12", "12.0", "12.00"} <= forms


def test_allowed_forms_sign_matters():
    forms = allowed_forms([-5.0])
    assert "-5" in forms and "-5.0" in forms and "-5.00" in forms
    assert "5" not in forms and "5.0" not in forms and "5.00" not in forms


def test_extract_numbers_ignores_unit_glued_tokens():
    assert extract_numbers("F0 // 16k and -3.5 st") == ["-3.5"]


def test_check_numbers_includes_field_name_and_dedupes():
    payload = {"metrics": {"pitch": {"f0_median_hz": 120.0}}, "transcript_derived": None, "comparison": None}
    out = {
        "what_improved": [],
        "what_is_lacking": ["99 is invented", "99 again"],
        "next_steps": [],
        "marked_up_example": "",
    }
    warnings = check_numbers(out, payload)
    assert warnings == ["number 99 in what_is_lacking does not match any metric value"]


def test_check_numbers_uses_transcript_derived_and_comparison():
    payload = {
        "metrics": {},
        "transcript_derived": {"words_per_min": 145.0},
        "comparison": {"f0_range_st_delta": -2.0},
    }
    out = {
        "what_improved": ["145 words per minute"],
        "what_is_lacking": ["down -2 st versus the previous recording"],
        "next_steps": [],
        "marked_up_example": "",
    }
    assert check_numbers(out, payload) == []
