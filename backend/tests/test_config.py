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
    assert cfg.analysis.min_duration_s == 2.0
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


def test_transcription_and_clarity_sections_load():
    cfg = load_config()
    assert cfg.transcription.model_size == "small"
    assert cfg.transcription.compute_type == "int8"
    assert cfg.transcription.beam_size == 5
    assert cfg.transcription.language == "en"
    assert cfg.transcription.no_speech_exclude_prob == 0.6
    assert cfg.transcription.fillers == ["um", "uh", "like", "basically", "actually", "you know", "so"]
    assert cfg.clarity.low_conf_word_prob == 0.5
    assert cfg.clarity.word_final_drop_db == 6
    assert cfg.clarity.word_final_tail_fraction == 0.3
    assert cfg.clarity.min_word_duration_s == 0.25
    assert cfg.clarity.rushed_syl_per_sec == 7
    assert cfg.clarity.rushed_run_min_words == 3
    assert cfg.clarity.low_logprob_segment == -1.0


def test_config_hash_ignores_transcription_and_clarity():
    src = load_config()
    changed = src.model_copy(deep=True)
    changed.transcription.beam_size = 1
    changed.clarity.rushed_syl_per_sec = 99
    assert config_hash(src) == config_hash(changed)


def test_six_decimal_fields_include_transcript_ratios():
    from vocal_coach.analysis.serialise import SIX_DECIMAL_FIELDS
    for name in ("probability", "avg_logprob", "no_speech_prob", "low_conf_word_fraction",
                 "word_final_drop_fraction", "rushed_word_fraction", "low_logprob_segment_fraction"):
        assert name in SIX_DECIMAL_FIELDS


def test_empty_filler_rejected_at_load():
    import pytest
    from vocal_coach.config import TranscriptionConfig
    with pytest.raises(ValueError):
        TranscriptionConfig(model_size="small", compute_type="int8", beam_size=5, language="en", no_speech_exclude_prob=0.6, fillers=["um", " "])


def test_comparison_section_loads():
    cfg = load_config()
    assert cfg.comparison.min_meaningful_change_pct == 5
    assert cfg.comparison.directions["pitch.f0_range_st"] == "up_good"
    assert cfg.comparison.directions["phrasing.pauses_per_min"] == "neutral"
    assert cfg.comparison.directions["transcript.derived.clarity.rushed_word_fraction"] == "down_good"
    assert len(cfg.comparison.directions) == 15


def test_comparison_direction_must_be_known():
    import pytest
    from vocal_coach.config import ComparisonConfig
    with pytest.raises(ValueError):
        ComparisonConfig(min_meaningful_change_pct=5, directions={"x": "sideways"})


def test_config_hash_ignores_comparison():
    src = load_config()
    changed = src.model_copy(deep=True)
    changed.comparison.min_meaningful_change_pct = 50
    assert config_hash(src) == config_hash(changed)


def test_comparison_min_meaningful_change_pct_must_be_positive():
    import pytest
    from vocal_coach.config import ComparisonConfig
    with pytest.raises(ValueError):
        ComparisonConfig(min_meaningful_change_pct=0, directions={})


def test_llm_config_loaded_and_not_in_hash(cfg):
    assert cfg.llm.provider in {"openai_compatible", "anthropic"}
    assert cfg.llm.timeout_s == 120
    from vocal_coach.config import config_hash
    changed = cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"model": "other"})})
    assert config_hash(changed) == config_hash(cfg)


def test_llm_config_defaults_when_section_missing():
    from vocal_coach.config import LLMConfig
    defaults = LLMConfig()
    assert defaults.enabled is False
    assert defaults.provider == "openai_compatible"
    assert defaults.timeout_s == 120.0
    assert defaults.allowed_models == []
