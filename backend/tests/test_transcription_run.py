import json
import os
from pathlib import Path

import pytest

from tests import synth
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.transcription.run import build_transcript, transcribe_file
from vocal_coach.transcription.schema import TRANSCRIPT_SCHEMA_VERSION, Transcript
from vocal_coach.transcription.transcriber import transcribe_wav


def _audio():
    a = synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)
    return synth.with_noise_floor(synth.concat(a, synth.silence(0.5), a))


def _fake():
    return FakeWhisper([
        seg(0.0, 3.0, " So basically I was like, you know, fine.", [
            word(0.0, 0.3, " So", 0.9), word(0.3, 0.8, " basically", 0.9), word(0.8, 1.0, " I", 0.9),
            word(1.0, 1.3, " was", 0.9), word(1.3, 1.6, " like,", 0.9), word(1.6, 1.8, " you", 0.9),
            word(1.8, 2.1, " know,", 0.9), word(2.1, 3.0, " fine.", 0.3),
        ]),
        seg(3.5, 6.5, " Um, that is all.", [
            word(3.5, 3.8, " Um,", 0.9), word(3.8, 4.4, " that", 0.9), word(4.4, 4.9, " is", 0.9), word(4.9, 6.5, " all.", 0.9),
        ], avg_logprob=-1.3),
    ])


def test_transcribe_file_end_to_end_with_fake_model(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", _audio())
    t = transcribe_file(wav, cfg, model=_fake())
    assert isinstance(t, Transcript)
    assert t.schema_version == TRANSCRIPT_SCHEMA_VERSION == "1.0"
    assert t.model == "small" and t.language == "en"
    assert t.derived.word_count == 12
    assert abs(t.derived.words_per_min - 12 / (6.5 / 60)) < 1e-6
    assert t.derived.filler_counts == {"um": 1, "uh": 0, "like": 1, "basically": 1, "actually": 0, "you know": 1, "so": 1}
    assert t.derived.filler_total == 5
    assert [w.word for w in t.derived.clarity.low_conf_words] == ["fine."]
    assert t.derived.clarity.segment_avg_logprob_mean is not None
    assert abs(t.derived.clarity.low_logprob_segment_fraction - 0.5) < 1e-9
    data = json.loads(to_canonical_json(t))
    assert set(data) == {"schema_version", "model", "language", "text", "segments", "words", "derived"}
    assert set(data["derived"]) == {"word_count", "words_per_min", "filler_counts", "filler_total", "fillers_per_min", "clarity"}


def test_duration_comes_from_audio_not_last_word(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", _audio())  # 6.5 s of audio
    fake = FakeWhisper([seg(0.0, 1.0, " Hi.", [word(0.0, 1.0, " Hi.", 0.9)])])
    t = transcribe_file(wav, cfg, model=fake)
    assert abs(t.derived.words_per_min - 1 / (6.5 / 60)) < 1e-6


def test_no_speech_gives_empty_transcript_that_serialises(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", synth.with_noise_floor(synth.silence(3.0)))
    t = transcribe_file(wav, cfg, model=FakeWhisper([]))
    assert t.text == "" and t.segments == [] and t.words == []
    assert t.derived.word_count == 0 and t.derived.words_per_min == 0.0
    assert t.derived.filler_total == 0 and t.derived.fillers_per_min == 0.0
    assert t.derived.clarity.low_conf_word_fraction is None
    to_canonical_json(t)


def test_build_transcript_reuses_given_tracks(cfg, tmp_path: Path):
    x = _audio()
    tracks = extract_tracks(synth.to_sound(x), cfg.analysis)
    raw = transcribe_wav(tmp_path / "unused.wav", cfg.transcription, _fake())
    t = build_transcript(raw, tracks, duration_s=tracks.duration_s, cfg=cfg)
    assert t.derived.word_count == 12


@pytest.mark.skipif(os.environ.get("VOCAL_COACH_REAL_WHISPER") != "1", reason="set VOCAL_COACH_REAL_WHISPER=1 to run the real model")
def test_real_whisper_on_synthetic_speech_does_not_crash(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", _audio())
    t = transcribe_file(wav, cfg)
    assert isinstance(t, Transcript)
    to_canonical_json(t)
