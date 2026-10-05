from datetime import datetime, timedelta, timezone

import pytest

from vocal_coach.config import ComparisonConfig
from vocal_coach.storage.comparison import ComparableAnalysis, ComparisonResult, compare, resolve_path

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
CFG = ComparisonConfig(min_meaningful_change_pct=5, directions={
    "pitch.f0_range_st": "up_good",
    "phrasing.long_pause_count_ge_1s": "down_good",
    "phrasing.pauses_per_min": "neutral",
    "transcript.derived.fillers_per_min": "down_good",
    "articulation.vowel_space.vowel_space_area_hz2": "up_good",
})


def _a(i, metrics, transcript=None, cfg="sha256:c1", day=0, version="0.1.0"):
    return ComparableAnalysis(id=f"a{i}", recorded_at=T0 + timedelta(days=day), config_hash=cfg,
                              analyser_version=version, metrics=metrics, transcript=transcript)


def _m(f0_range=10.0, long_pauses=4, ppm=12.0, area=900000.0):
    return {"pitch": {"f0_range_st": f0_range}, "phrasing": {"long_pause_count_ge_1s": long_pauses, "pauses_per_min": ppm},
            "articulation": {"vowel_space": {"vowel_space_area_hz2": area}}}


def _t(fpm=3.0):
    return {"derived": {"fillers_per_min": fpm, "clarity": {}}}


def test_resolve_path_metrics_and_transcript():
    a = _a(1, _m(), _t(2.5))
    assert resolve_path(a, "pitch.f0_range_st") == 10.0
    assert resolve_path(a, "transcript.derived.fillers_per_min") == 2.5
    assert resolve_path(a, "pitch.nope") is None
    assert resolve_path(_a(2, _m(), None), "transcript.derived.fillers_per_min") is None
    assert resolve_path(_a(3, {"pitch": {"f0_range_st": True}}), "pitch.f0_range_st") is None  # bool is not a metric


def test_verdicts_and_arrows():
    r = compare([_a(1, _m(10.0, 4, 12.0), _t(3.0)), _a(2, _m(12.0, 2, 12.3), _t(3.0), day=1)], CFG)
    assert isinstance(r, ComparisonResult)
    rows = {row.path: row for row in r.rows}
    assert rows["pitch.f0_range_st"].verdict == "improved" and rows["pitch.f0_range_st"].arrow == "↑"
    assert rows["pitch.f0_range_st"].delta == 2.0 and rows["pitch.f0_range_st"].step_deltas == [2.0]
    assert rows["phrasing.long_pause_count_ge_1s"].verdict == "improved" and rows["phrasing.long_pause_count_ge_1s"].arrow == "↓"
    assert rows["phrasing.pauses_per_min"].verdict == "unchanged"  # 2.5 % < 5 %
    assert rows["phrasing.pauses_per_min"].arrow == "→"
    assert rows["transcript.derived.fillers_per_min"].verdict == "unchanged" and rows["transcript.derived.fillers_per_min"].delta == 0.0


def test_neutral_direction_with_meaningful_change():
    r = compare([_a(1, _m(ppm=10.0)), _a(2, _m(ppm=20.0), day=1)], CFG)
    row = next(x for x in r.rows if x.path == "phrasing.pauses_per_min")
    assert row.verdict == "neutral" and row.arrow == "↑"


def test_worsened_down_good():
    r = compare([_a(1, _m(long_pauses=2)), _a(2, _m(long_pauses=5), day=1)], CFG)
    row = next(x for x in r.rows if x.path == "phrasing.long_pause_count_ge_1s")
    assert row.verdict == "worsened" and row.arrow == "↑"


def test_zero_baseline_does_not_divide_by_zero():
    same = compare([_a(1, _m(long_pauses=0)), _a(2, _m(long_pauses=0), day=1)], CFG)
    assert next(x for x in same.rows if x.path == "phrasing.long_pause_count_ge_1s").verdict == "unchanged"
    worse = compare([_a(1, _m(long_pauses=0)), _a(2, _m(long_pauses=1), day=1)], CFG)
    assert next(x for x in worse.rows if x.path == "phrasing.long_pause_count_ge_1s").verdict == "worsened"


def test_missing_metric_is_unavailable_not_error():
    r = compare([_a(1, _m(), None), _a(2, _m(), _t(2.0), day=1)], CFG)
    row = next(x for x in r.rows if x.path == "transcript.derived.fillers_per_min")
    assert row.values == [None, 2.0] and row.delta is None and row.step_deltas == [None]
    assert row.verdict == "unavailable" and row.arrow == "—"  # only one non-None value
    assert row.partial is True
    assert next(x for x in r.rows if x.path == "pitch.f0_range_st").verdict == "unchanged"


def test_sorted_by_recorded_at_and_config_mismatch_flag():
    later = _a(1, _m(10.0), day=5)
    earlier = _a(2, _m(8.0), day=0, cfg="sha256:other")
    r = compare([later, earlier], CFG)
    assert r.analysis_ids == ["a2", "a1"]
    assert r.config_mismatch is True
    assert next(x for x in r.rows if x.path == "pitch.f0_range_st").delta == 2.0
    assert compare([_a(1, _m()), _a(2, _m(), day=1)], CFG).config_mismatch is False


def test_three_recordings_steps_and_trend():
    r = compare([_a(1, _m(10.0)), _a(2, _m(11.0), day=1), _a(3, _m(9.0), day=2)], CFG)
    row = next(x for x in r.rows if x.path == "pitch.f0_range_st")
    assert row.values == [10.0, 11.0, 9.0] and row.step_deltas == [1.0, -2.0] and row.delta == -1.0
    assert row.verdict == "worsened"
    assert [p.value for p in r.trend["pitch.f0_range_st"]] == [10.0, 11.0, 9.0]
    assert [p.analysis_id for p in r.trend["pitch.f0_range_st"]] == ["a1", "a2", "a3"]
    assert set(r.trend) == set(CFG.directions)


def test_requires_two_analyses():
    with pytest.raises(ValueError):
        compare([_a(1, _m())], CFG)


def test_nan_and_inf_are_unavailable():
    nan_result = compare([
        _a(1, {"pitch": {"f0_range_st": float("nan")}}),
        _a(2, {"pitch": {"f0_range_st": 10.0}}, day=1)
    ], CFG)
    nan_row = next(x for x in nan_result.rows if x.path == "pitch.f0_range_st")
    assert nan_row.verdict == "unavailable" and nan_row.arrow == "—" and nan_row.delta is None

    inf_result = compare([
        _a(1, {"pitch": {"f0_range_st": 10.0}}),
        _a(2, {"pitch": {"f0_range_st": float("inf")}}, day=1)
    ], CFG)
    inf_row = next(x for x in inf_result.rows if x.path == "pitch.f0_range_st")
    assert inf_row.verdict == "unavailable" and inf_row.arrow == "—" and inf_row.delta is None


def _f0(*values):
    return [_a(i, {"pitch": {"f0_range_st": v}}, day=i) for i, v in enumerate(values)]


def _f0_row(result):
    return next(x for x in result.rows if x.path == "pitch.f0_range_st")


def test_partial_series_uses_first_and_last_available_values():
    row = _f0_row(compare(_f0(None, 2.0, 3.0), CFG))
    assert row.values == [None, 2.0, 3.0] and row.step_deltas == [None, 1.0]
    assert row.delta == 1.0 and row.partial is True
    assert row.verdict == "improved" and row.arrow == "↑"
    gap = _f0_row(compare(_f0(2.0, None, 3.0), CFG))
    assert gap.delta == 1.0 and gap.partial is True and gap.step_deltas == [None, None]


def test_series_with_one_available_value_is_unavailable_and_partial():
    row = _f0_row(compare(_f0(None, None, 5.0), CFG))
    assert row.verdict == "unavailable" and row.delta is None and row.partial is True and row.arrow == "—"


def test_complete_series_is_not_partial():
    assert _f0_row(compare(_f0(1.0, 2.0), CFG)).partial is False


def test_same_recorded_at_ties_break_by_id():
    b = ComparableAnalysis(id="b", recorded_at=T0, config_hash="c", analyser_version="0.1.0", metrics={}, transcript=None)
    a = ComparableAnalysis(id="a", recorded_at=T0, config_hash="c", analyser_version="0.1.0", metrics={}, transcript=None)
    assert compare([b, a], CFG).analysis_ids == ["a", "b"]
    assert compare([a, b], CFG).analysis_ids == ["a", "b"]


def test_analyser_version_mismatch_flag():
    r = compare([_a(1, _m(), version="0.1.0"), _a(2, _m(), day=1, version="0.2.0")], CFG)
    assert r.analyser_version_mismatch is True and r.config_mismatch is False
    assert compare([_a(1, _m()), _a(2, _m(), day=1)], CFG).analyser_version_mismatch is False


def test_naive_recorded_at_rejected():
    with pytest.raises(ValueError):
        ComparableAnalysis(id="x", recorded_at=datetime(2026, 10, 1), config_hash="c", analyser_version="0.1.0",
                           metrics={}, transcript=None)


def test_file_names_filled_in_recorded_at_order():
    a = _a(1, _m(), day=1)
    a.file_name = "second.wav"
    b = _a(2, _m(), day=0)
    b.file_name = "first.wav"
    r = compare([a, b], CFG)
    assert r.analysis_ids == ["a2", "a1"]
    assert r.file_names == ["first.wav", "second.wav"]


def test_file_name_defaults_to_none():
    r = compare([_a(1, _m()), _a(2, _m(), day=1)], CFG)
    assert r.file_names == [None, None]


def test_near_zero_delta_at_default_precision_is_unchanged_even_if_percentage_significant():
    # Default precision is 1 decimal. -0.04 rounds to 0.0 (unchanged); -0.06 rounds to -0.1 (not
    # near-zero), so it falls through to the percentage rule and should read as worsened for an
    # up_good metric with a small baseline where the percentage threshold does not save it.
    cfg = ComparisonConfig(min_meaningful_change_pct=5, directions={"pitch.f0_range_st": "up_good"})
    small_change = compare(_f0(1.00, 0.96), cfg)
    assert _f0_row(small_change).verdict == "unchanged" and _f0_row(small_change).delta == pytest.approx(-0.04)
    bigger_change = compare(_f0(1.00, 0.94), cfg)
    row = _f0_row(bigger_change)
    assert row.delta == pytest.approx(-0.06) and row.verdict == "worsened" and row.arrow == "↓"


def test_modulation_depth_uses_two_decimal_precision():
    cfg = ComparisonConfig(min_meaningful_change_pct=5, directions={"articulation.modulation_depth": "up_good"})

    def _mod(a, b):
        return compare(
            [_a(1, {"articulation": {"modulation_depth": a}}), _a(2, {"articulation": {"modulation_depth": b}}, day=1)],
            cfg,
        )

    unchanged = next(x for x in _mod(0.100, 0.096).rows if x.path == "articulation.modulation_depth")
    assert unchanged.verdict == "unchanged" and unchanged.delta == pytest.approx(-0.004)
    worsened = next(x for x in _mod(0.100, 0.094).rows if x.path == "articulation.modulation_depth")
    assert worsened.verdict == "worsened" and worsened.delta == pytest.approx(-0.006)


def test_count_metric_zero_delta_is_unchanged():
    cfg = ComparisonConfig(min_meaningful_change_pct=5, directions={"energy.trailing_off_count": "down_good"})
    r = compare(
        [_a(1, {"energy": {"trailing_off_count": 3}}), _a(2, {"energy": {"trailing_off_count": 3}}, day=1)], cfg,
    )
    row = next(x for x in r.rows if x.path == "energy.trailing_off_count")
    assert row.delta == 0.0 and row.verdict == "unchanged" and row.arrow == "→"
