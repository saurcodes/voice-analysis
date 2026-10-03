from pathlib import Path

from vocal_coach.config import AppConfig, config_hash, load_config


def test_load_default_config_has_spec_values():
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.analysis.pitch_floor_hz == 75
    assert cfg.analysis.pitch_ceiling_hz == 350
    assert cfg.analysis.time_step_s == 0.01
    assert cfg.analysis.silence_threshold_db == -25
    assert cfg.analysis.intonation_threshold_st == 1.5
    assert cfg.articulation.hf_band_hz == (2000, 8000)
    assert cfg.articulation.formant_max_hz == 5500


def test_config_hash_is_stable_and_prefixed():
    a = config_hash(load_config())
    b = config_hash(load_config())
    assert a == b
    assert a.startswith("sha256:")
    assert len(a) == len("sha256:") + 64


def test_config_hash_changes_when_analysis_value_changes(tmp_path: Path):
    src = load_config()
    changed = src.model_copy(deep=True)
    changed.analysis.pitch_ceiling_hz = 400
    assert config_hash(src) != config_hash(changed)


def test_config_hash_ignores_non_analysis_sections():
    src = load_config()
    changed = src.model_copy(deep=True)
    changed.raw["llm"]["seed"] = 7
    assert config_hash(src) == config_hash(changed)
