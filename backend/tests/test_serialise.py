import json
import math

from pydantic import BaseModel

from vocal_coach.analysis.serialise import round_floats, to_canonical_json


class Inner(BaseModel):
    voiced_fraction: float
    f0_median_hz: float
    maybe: float | None


class Outer(BaseModel):
    inner: Inner
    values: list[float]
    jitter_local: float


def test_round_floats_uses_six_decimals_for_ratio_fields_and_four_otherwise():
    data = {"voiced_fraction": 0.123456789, "f0_median_hz": 118.123456, "jitter_local": 0.0123456789,
            "values": [1.23456789, 2.0], "nested": {"modulation_depth": 0.98765432}}
    out = round_floats(data)
    assert out["voiced_fraction"] == 0.123457
    assert out["f0_median_hz"] == 118.1235
    assert out["jitter_local"] == 0.012346
    assert out["values"] == [1.2346, 2.0]
    assert out["nested"]["modulation_depth"] == 0.987654


def test_nan_and_inf_become_null():
    out = round_floats({"a": math.nan, "b": math.inf, "c": [math.nan, 1.0]})
    assert out == {"a": None, "b": None, "c": [None, 1.0]}


def test_canonical_json_sorted_and_compact():
    obj = Outer(inner=Inner(voiced_fraction=0.5, f0_median_hz=100.0, maybe=None), values=[1.0], jitter_local=0.01)
    s = to_canonical_json(obj)
    assert s == json.dumps(json.loads(s), sort_keys=True, separators=(",", ":"))
    assert "\n" not in s and " " not in s
    assert '"maybe":null' in s
