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


def _a(i, metrics, transcript=None, cfg="sha256:c1", day=0):
    return ComparableAnalysis(id=f"a{i}", recorded_at=T0 + timedelta(days=day), config_hash=cfg,
                              metrics=metrics, transcript=transcript)


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
    assert row.verdict == "unavailable" and row.arrow == "—"
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
