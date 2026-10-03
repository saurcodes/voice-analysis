from pathlib import Path

from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.transcription.transcriber import RawTranscription, transcribe_wav


def test_transcribe_converts_segments_and_words(cfg, tmp_path: Path):
    fake = FakeWhisper([
        seg(0.0, 1.2, " Hello there.", [word(0.0, 0.5, " Hello", 0.95), word(0.6, 1.2, " there.", 0.8)]),
        seg(1.5, 2.0, " Um.", [word(1.5, 2.0, " Um.", 0.4)], avg_logprob=-1.2),
    ])
    raw = transcribe_wav(tmp_path / "x.wav", cfg.transcription, fake)
    assert isinstance(raw, RawTranscription)
    assert raw.language == "en"
    assert [s.text for s in raw.segments] == ["Hello there.", "Um."]
    assert raw.segments[1].avg_logprob == -1.2
    assert [w.word for w in raw.words] == ["Hello", "there.", "Um."]
    assert raw.words[2].probability == 0.4
    assert raw.text == "Hello there. Um."


def test_transcribe_passes_fixed_decoding_settings(cfg, tmp_path: Path):
    fake = FakeWhisper([])
    transcribe_wav(tmp_path / "x.wav", cfg.transcription, fake)
    kw = fake.calls[0]
    assert kw["temperature"] == 0.0
    assert kw["beam_size"] == cfg.transcription.beam_size == 5
    assert kw["word_timestamps"] is True
    assert kw["vad_filter"] is False
    assert kw["language"] == "en"


def test_language_none_means_autodetect(cfg, tmp_path: Path):
    tcfg = cfg.transcription.model_copy(update={"language": None})
    fake = FakeWhisper([], language="fr")
    raw = transcribe_wav(tmp_path / "x.wav", tcfg, fake)
    assert fake.calls[0]["language"] is None
    assert raw.language == "fr"


def test_segment_without_words_is_kept(cfg, tmp_path: Path):
    fake = FakeWhisper([seg(0.0, 1.0, " (music)", None)])
    raw = transcribe_wav(tmp_path / "x.wav", cfg.transcription, fake)
    assert len(raw.segments) == 1
    assert raw.words == []
