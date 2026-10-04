import json

from vocal_coach.llm.payload import CAP, build_payload, summarise_timeline
from vocal_coach.llm.prompts import load_system_prompt


def _metrics_with_per_phrase_and_long_pauses(n_pauses: int) -> dict:
    return {
        "intonation": {
            "up_count": 1,
            "down_count": 0,
            "flat_count": 0,
            "per_phrase": [{"start_s": 0.0, "end_s": 1.0, "end_delta_st": 2.0, "class": "up"}],
        },
        "energy": {
            "trailing_off_count": 1,
            "per_phrase_end_drop_db": [1.5, 2.5],
        },
        "phrasing": {
            "pause_count": n_pauses,
            "long_pauses": [
                {"start_s": float(i), "end_s": float(i) + 1.2, "duration_s": 1.2}
                for i in range(n_pauses)
            ],
        },
    }


def test_drops_per_phrase_keys_caps_long_pauses_keeps_text_excludes_words():
    metrics = _metrics_with_per_phrase_and_long_pauses(25)
    transcript = {
        "text": "hello world",
        "segments": [{"start_s": 0.0, "end_s": 1.0, "text": "hello world"}],
        "words": [{"start_s": 0.0, "end_s": 0.5, "word": "hello", "probability": 0.9}],
        "derived": {"word_count": 2, "words_per_min": 100.0},
    }

    payload = build_payload(metrics, transcript, None, None)

    assert "per_phrase" not in payload["metrics"]["intonation"]
    assert "per_phrase_end_drop_db" not in payload["metrics"]["energy"]
    assert len(payload["metrics"]["phrasing"]["long_pauses"]) == CAP == 20
    assert payload["transcript_text"] == "hello world"
    assert "words" not in payload
    assert "segments" not in payload
    assert payload["comparison"] is None

    # original dicts are untouched (deep copy, not pruning in place)
    assert len(metrics["phrasing"]["long_pauses"]) == 25
    assert "per_phrase" in metrics["intonation"]
    assert "words" in transcript


def test_transcript_none_gives_empty_text_and_none_derived():
    payload = build_payload({"pitch": {"f0_median_hz": 120.0}}, None, None, None)
    assert payload["transcript_text"] == ""
    assert payload["transcript_derived"] is None
    assert payload["comparison"] is None
    assert payload["speaker_context"] is None


def test_comparison_and_speaker_context_pass_through():
    comparison = {"f0_range_st_delta": 1.2}
    payload = build_payload({}, None, comparison, "reads quickly when nervous")
    assert payload["comparison"] == comparison
    assert payload["speaker_context"] == "reads quickly when nervous"


def test_caps_lists_under_transcript_derived_at_any_depth():
    transcript = {
        "text": "hi there",
        "words": [{"word": "hi"}],
        "derived": {
            "word_count": 2,
            "clarity": {
                "eaten_words": [{"word": f"w{i}", "drop_db": 1.0} for i in range(25)],
                "rushed_runs": [{"text": f"r{i}"} for i in range(21)],
                "low_conf_words": [{"word": f"c{i}"} for i in range(30)],
            },
        },
    }

    payload = build_payload({}, transcript, None, None)
    clarity = payload["transcript_derived"]["clarity"]
    assert len(clarity["eaten_words"]) == 20
    assert len(clarity["rushed_runs"]) == 20
    assert len(clarity["low_conf_words"]) == 20


def test_missing_transcript_text_defaults_to_empty_string():
    payload = build_payload({}, {"derived": {"word_count": 0}}, None, None)
    assert payload["transcript_text"] == ""
    assert payload["transcript_derived"] == {"word_count": 0}


def test_load_system_prompt_returns_bundled_markdown():
    text = load_system_prompt()
    assert text.startswith("You are a vocal delivery coach.")
    assert "marked_up_example" in text
    assert chr(0x2014) not in text


def _timeline(n: int) -> dict:
    return {
        "window_s": 5.0,
        "windows": [
            {"start_s": i * 5.0, "end_s": i * 5.0 + 5.0, "f0_median_hz": 110.0 + (i % 40) * 1.2345,
             "f0_sd_st": 2.0 + (i % 7) * 0.111, "intensity_median_db": 60.0 + (i % 11) * 0.5}
            for i in range(n)
        ],
    }


def test_long_recording_payload_is_small():
    transcript = {"text": " ".join(f"word{i}" for i in range(13_000)), "derived": {"word_count": 13_000}}
    payload = build_payload({"timeline": _timeline(360), "pitch": {"f0_median_hz": 120.0}}, transcript, None, None)

    assert "timeline" not in payload["metrics"]
    assert payload["metrics"]["timeline_summary"]["window_count"] == 360
    assert len(json.dumps(payload, sort_keys=True).encode("utf-8")) < 40_000


def test_timeline_summary_values_skip_nulls():
    timeline = {
        "window_s": 2.0,
        "windows": [
            {"start_s": 0.0, "end_s": 2.0, "f0_median_hz": 100.0, "f0_sd_st": None, "intensity_median_db": 60.0},
            {"start_s": 2.0, "end_s": 4.0, "f0_median_hz": None, "f0_sd_st": None, "intensity_median_db": 70.0},
            {"start_s": 4.0, "end_s": 6.0, "f0_median_hz": 140.0, "f0_sd_st": None, "intensity_median_db": 65.5},
            {"start_s": 6.0, "end_s": 8.0, "f0_median_hz": 120.0, "f0_sd_st": None, "intensity_median_db": None},
        ],
    }
    assert summarise_timeline(timeline) == {
        "window_s": 2.0,
        "window_count": 4,
        "f0_median_hz": {"min": 100.0, "p50": 120.0, "max": 140.0},
        "f0_sd_st": {"min": None, "p50": None, "max": None},
        "intensity_median_db": {"min": 60.0, "p50": 65.5, "max": 70.0},
    }


def test_build_payload_replaces_timeline_with_summary():
    payload = build_payload({"timeline": {"window_s": 1.0, "windows": []}}, None, None, None)
    assert payload["metrics"] == {"timeline_summary": {
        "window_s": 1.0, "window_count": 0,
        "f0_median_hz": {"min": None, "p50": None, "max": None},
        "f0_sd_st": {"min": None, "p50": None, "max": None},
        "intensity_median_db": {"min": None, "p50": None, "max": None},
    }}


def test_transcript_truncated_to_max_words_with_flags():
    transcript = {"text": "one two three four five", "derived": None}
    payload = build_payload({}, transcript, None, None, max_transcript_words=3)
    assert payload["transcript_text"] == "one two three"
    assert payload["transcript_truncated"] is True
    assert payload["transcript_word_count"] == 5


def test_transcript_not_truncated_flags_present():
    payload = build_payload({}, {"text": "one two"}, None, None, max_transcript_words=3)
    assert payload["transcript_text"] == "one two"
    assert payload["transcript_truncated"] is False
    assert payload["transcript_word_count"] == 2

    empty = build_payload({}, None, None, None)
    assert empty["transcript_truncated"] is False and empty["transcript_word_count"] == 0
