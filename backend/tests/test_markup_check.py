from vocal_coach.llm.markup_check import check_marked_up_example, demark


def test_matching_example_with_marks_returns_none():
    transcript = "So we will win today, right?"
    example = "we WILL win // today ↘."
    assert check_marked_up_example(example, transcript) is None


def test_mismatched_example_returns_warning():
    transcript = "So we will win today, right?"
    example = "we lose today"
    assert check_marked_up_example(example, transcript) == "marked_up_example does not match the transcript"


def test_no_transcript_returns_warning_when_example_present():
    assert check_marked_up_example("we lose today", None) == "no transcript available for marked_up_example"
    assert check_marked_up_example("we lose today", "") == "no transcript available for marked_up_example"


def test_empty_example_returns_warning_when_transcript_present():
    transcript = "So we will win today, right?"
    assert check_marked_up_example("", transcript) == "marked_up_example is empty"
    assert check_marked_up_example("   ", transcript) == "marked_up_example is empty"


def test_empty_example_with_no_transcript_returns_none():
    assert check_marked_up_example("", None) is None
    assert check_marked_up_example("   ", "") is None


def test_punctuation_only_example_returns_mismatch_warning():
    transcript = "So we will win today, right?"
    assert check_marked_up_example("!!!", transcript) == "marked_up_example does not match the transcript"
    assert check_marked_up_example("// ↘", transcript) == "marked_up_example does not match the transcript"


def test_demark_removes_marks_lowercases_and_keeps_apostrophes_inside_words():
    assert demark("Don't // stop ↘ now.") == ["don't", "stop", "now"]


def test_demark_strips_leading_and_trailing_quote_punctuation():
    assert demark("'hello' -- world!") == ["hello", "world"]
