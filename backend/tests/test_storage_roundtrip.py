import json
from datetime import timedelta

import pytest

from tests import synth
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.analysis.analyser import analyse_wav
from vocal_coach.analysis.schema import SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.config import config_hash
from vocal_coach.storage import repo
from vocal_coach.storage.comparison import compare, from_row
from vocal_coach.storage.db import create_all, make_engine, make_session_factory
from vocal_coach.storage.models import utcnow
from vocal_coach.transcription.run import transcribe_file


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


def _speech(tmp_path, name, f0):
    a = synth.am(synth.vowel(500, 1500, f0, 3.0), 4.0)
    x = synth.with_noise_floor(synth.concat(a, synth.silence(0.6), a))
    return synth.write_wav(tmp_path / name, x)


def _fake():
    return FakeWhisper([seg(0.0, 3.0, " So basically yes.", [word(0.0, 0.3, " So", 0.9), word(0.3, 0.8, " basically", 0.9), word(0.8, 1.2, " yes.", 0.9)])])


def test_metrics_and_transcript_round_trip_and_compare(cfg, session, tmp_path):
    user = repo.upsert_user(session, "sub", None, None)
    rows = []
    for i, f0 in enumerate((110, 140)):
        wav = _speech(tmp_path, f"r{i}.wav", f0)
        src = SourceInfo(file_name=wav.name, drive_file_id=None, drive_modified_time=None, content_sha256=str(i) * 64,
                         duration_s=6.6, original_channels=1, original_sample_rate=16000)
        report = analyse_wav(wav, cfg, src)
        transcript = transcribe_file(wav, cfg, model=_fake())
        rows.append(repo.create_analysis(
            session, user.id, file_name=wav.name, drive_file_id=None, content_sha256=str(i) * 64,
            recorded_at=utcnow() + timedelta(days=i), analyser_version=report.analyser_version,
            config_hash=report.config_hash, metrics_json=json.loads(to_canonical_json(report)),
            transcript_json=json.loads(to_canonical_json(transcript)),
        ))
    loaded = [repo.get_analysis(session, user.id, r.id) for r in rows]
    assert loaded[0].config_hash == config_hash(cfg)
    assert loaded[0].metrics_json["pitch"]["f0_median_hz"] is not None
    assert loaded[1].transcript_json["derived"]["filler_total"] == 2

    result = compare([from_row(r) for r in loaded], cfg.comparison)
    assert result.config_mismatch is False
    verdicts = {r.path: r.verdict for r in result.rows}
    assert verdicts["transcript.derived.fillers_per_min"] == "unchanged"
    assert all(v != "unavailable" for p, v in verdicts.items() if p.startswith("pitch."))
    # Every configured path resolves to a number or None without raising.
    assert set(result.trend) == set(cfg.comparison.directions)
