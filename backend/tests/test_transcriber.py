import numpy as np
import pytest

from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.transcription import transcriber
from vocal_coach.transcription.transcriber import RawTranscription, get_model, transcribe_audio


def _silence():
    return np.zeros(16000, dtype=np.float32)


def test_transcribe_converts_segments_and_words(cfg):
    fake = FakeWhisper([
        seg(0.0, 1.2, " Hello there.", [word(0.0, 0.5, " Hello", 0.95), word(0.6, 1.2, " there.", 0.8)]),
        seg(1.5, 2.0, " Um.", [word(1.5, 2.0, " Um.", 0.4)], avg_logprob=-1.2),
    ])
    raw = transcribe_audio(_silence(), 16000, cfg.transcription, fake)
    assert isinstance(raw, RawTranscription)
    assert raw.language == "en"
    assert [s.text for s in raw.segments] == ["Hello there.", "Um."]
    assert raw.segments[1].avg_logprob == -1.2
    assert [w.word for w in raw.words] == ["Hello", "there.", "Um."]
    assert raw.words[2].probability == 0.4
    assert raw.text == "Hello there. Um."
    assert raw.word_segment_index == [0, 0, 1]


def test_transcribe_passes_fixed_decoding_settings(cfg):
    fake = FakeWhisper([])
    transcribe_audio(_silence(), 16000, cfg.transcription, fake)
    kw = fake.calls[0]
    assert kw["temperature"] == 0.0
    assert kw["beam_size"] == cfg.transcription.beam_size == 5
    assert kw["word_timestamps"] is True
    assert kw["vad_filter"] is False
    assert kw["language"] == "en"
    assert kw["condition_on_previous_text"] is False


def test_language_none_means_autodetect(cfg):
    tcfg = cfg.transcription.model_copy(update={"language": None})
    fake = FakeWhisper([], language="fr")
    raw = transcribe_audio(_silence(), 16000, tcfg, fake)
    assert fake.calls[0]["language"] is None
    assert raw.language == "fr"


def test_segment_without_words_is_kept(cfg):
    fake = FakeWhisper([seg(0.0, 1.0, " (music)", None)])
    raw = transcribe_audio(_silence(), 16000, cfg.transcription, fake)
    assert len(raw.segments) == 1
    assert raw.words == []


def test_whisper_receives_float32_array_identical_to_input(cfg):
    audio = np.linspace(-0.5, 0.5, 16000, dtype=np.float64)
    fake = FakeWhisper([])
    transcribe_audio(audio, 16000, cfg.transcription, fake)
    got = fake.audio[0]
    assert got.dtype == np.float32
    assert got.ndim == 1
    assert np.array_equal(got, audio.astype(np.float32))


def test_non_16k_sample_rate_raises(cfg):
    with pytest.raises(ValueError):
        transcribe_audio(np.zeros(44100, dtype=np.float32), 44100, cfg.transcription, FakeWhisper([]))


def test_get_model_caches_per_config(cfg, monkeypatch):
    loads = []

    def fake_load(c):
        loads.append(c)
        return FakeWhisper([])

    monkeypatch.setattr(transcriber, "load_model", fake_load)
    monkeypatch.setattr(transcriber, "_MODEL_CACHE", {})
    first = get_model(cfg.transcription)
    second = get_model(cfg.transcription)
    get_model(cfg.transcription.model_copy(update={"compute_type": "float32"}))
    assert first is second
    assert len(loads) == 2
