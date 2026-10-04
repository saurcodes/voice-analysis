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


def test_allowed_forms_negative_value_also_allows_unsigned_forms():
    forms = allowed_forms([-5.0])
    assert "-5" in forms and "-5.0" in forms and "-5.00" in forms
    assert "5" in forms and "5.0" in forms and "5.00" in forms


def test_allowed_forms_positive_value_does_not_allow_negative_forms():
    forms = allowed_forms([5.0])
    assert "-5" not in forms and "-5.0" not in forms


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


def _payload(metrics=None, transcript_text="", comparison=None):
    return {"metrics": metrics or {}, "transcript_text": transcript_text,
            "transcript_derived": None, "comparison": comparison}


def _out(lacking=(), steps=(), example=""):
    return {"what_improved": [], "what_is_lacking": list(lacking), "next_steps": list(steps),
            "marked_up_example": example}


def test_numeric_leaves_keeps_original_type():
    leaves = numeric_leaves({"a": 3, "b": 2.5})
    assert [type(v) for v in leaves] == [int, float]


def test_exact_four_and_six_decimal_citations_pass():
    payload = _payload({"pitch": {"f0_sd_st": 31.2979, "jitter": 0.123456}})
    assert check_numbers(_out(["sd 31.2979 st", "jitter 0.123456"]), payload) == []


def test_scientific_float_cited_as_decimal_passes():
    payload = _payload({"quality": {"noise": 1e-05}})
    assert check_numbers(_out(["noise floor 0.00001"]), payload) == []


def test_thousands_separator_matches_as_one_token_and_passes():
    assert extract_numbers("about 1,200 words") == ["1,200"]
    payload = _payload({"transcript": {"word_count": 1200}})
    assert check_numbers(_out(["you spoke 1,200 words", "1200 words"]), payload) == []


def test_transcript_number_in_marked_up_example_is_not_flagged():
    payload = _payload({}, transcript_text="We grew 47 percent in 2019.")
    out = _out(example="we grew 47 percent // in 2019")
    assert check_numbers(out, payload) == []


def test_transcript_numbers_are_allowed_in_scanned_fields():
    payload = _payload({}, transcript_text="We grew 47 percent.")
    assert check_numbers(_out(["when you said 47 percent"]), payload) == []


def test_prompt_numbers_pass_in_next_steps():
    assert check_numbers(_out(steps=["pause for 1 to 1.5 seconds"]), _payload()) == []


def test_small_counts_pass():
    assert check_numbers(_out(["you trailed off 3 times", "and 10 more"]), _payload()) == []


def test_negative_delta_cited_unsigned_passes():
    payload = _payload(comparison={"rows": [{"delta": -2.35}]})
    assert check_numbers(_out(["range fell by 2.35 st", "about 2.4 st"]), payload) == []


def test_invented_value_still_flagged():
    payload = _payload({"pitch": {"f0_range_st": 17.26}})
    warnings = check_numbers(_out(["range 17.5 st"]), payload)
    assert warnings == ["number 17.5 in what_is_lacking does not match any metric value"]


def test_year_absent_from_transcript_and_metrics_is_flagged():
    payload = _payload({"pitch": {"f0_range_st": 17.26}}, transcript_text="hello there")
    warnings = check_numbers(_out(["as in 2019"]), payload)
    assert warnings == ["number 2019 in what_is_lacking does not match any metric value"]
