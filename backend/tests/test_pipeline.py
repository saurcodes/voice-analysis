import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests import synth
from tests.conftest import requires_ffmpeg
from tests.fake_llm import FakeProvider
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.drive.errors import DriveNotConnected, DriveNotFound
from vocal_coach.llm.base import LLMError
from vocal_coach.pipeline import STAGES, JobRequest, run_pipeline
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.storage.db import create_all, make_engine, make_session_factory

VALID_COACHING = {
    "what_improved": ["steady pace"],
    "what_is_lacking": ["flat intonation"],
    "next_steps": ["vary pitch on key words"],
    "marked_up_example": "So yes.",
}


@pytest.fixture
def session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


def _speech():
    a = synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)
    return synth.with_noise_floor(synth.concat(a, synth.silence(0.6), a))


def _fake():
    return FakeWhisper([seg(0.0, 3.0, " So yes.", [word(0.0, 0.3, " So", 0.9), word(0.3, 0.8, " yes.", 0.9)])])


def _req(session, tmp_path, name="r.wav"):
    user = repo.upsert_user(session, "sub", None, None)
    job = repo.create_job(session, user.id)
    src = synth.write_wav(tmp_path / name, _speech())
    return JobRequest(job_id=job.id, user_id=user.id, source_path=src, file_name=name,
                      recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc)), user


def _drive_req(session, tmp_path, *, cached: bool = False):
    """A Drive-sourced JobRequest. `source_path` is the cache path; it is pre-populated with real
    audio when `cached` so the download stage should treat it as a hit and skip the downloader."""
    user = repo.upsert_user(session, "sub", None, None)
    job = repo.create_job(session, user.id)
    dest = tmp_path / "cache" / "file-1__2026-10-04T10-42-00.000Z.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if cached:
        synth.write_wav(dest, _speech())
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=dest, file_name="take.wav",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                     drive_file_id="file-1", drive_modified_time="2026-10-04T10:42:00.000Z")
    return req, user


@requires_ffmpeg
def test_pipeline_runs_all_stages_and_stores_analysis(cfg, session, tmp_path: Path):
    req, user = _req(session, tmp_path)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    seen: list[tuple[str, int]] = []
    analysis_id = run_pipeline(req, cfg, settings, session, lambda s, p: seen.append((s, p)), whisper_model=_fake())
    assert [s for s, _ in seen] == list(STAGES)
    assert [p for _, p in seen] == sorted(p for _, p in seen) and seen[-1] == ("done", 100)
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.metrics_json["pitch"]["f0_median_hz"] is not None
    assert row.transcript_json["derived"]["filler_total"] == 1
    assert not (tmp_path / "data" / "work" / str(req.job_id)).exists()  # work dir cleaned up


@requires_ffmpeg
def test_pipeline_dedupes_same_file_same_config(cfg, session, tmp_path: Path):
    req1, user = _req(session, tmp_path, "a.wav")
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    first = run_pipeline(req1, cfg, settings, session, lambda s, p: None, whisper_model=_fake())
    job2 = repo.create_job(session, user.id)
    req2 = JobRequest(job_id=job2.id, user_id=user.id, source_path=req1.source_path, file_name="a.wav",
                      recorded_at=req1.recorded_at)
    seen = []
    second = run_pipeline(req2, cfg, settings, session, lambda s, p: seen.append(s), whisper_model=_fake())
    assert second == first
    assert seen == ["download", "extract", "coach", "done"]  # no analyse/transcribe on a dedupe hit


@requires_ffmpeg
def test_pipeline_stores_analysis_before_coach_stage(cfg, session, tmp_path: Path):
    req, user = _req(session, tmp_path)
    req.source_sha256 = "c" * 64
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    stored_at_stage: dict[str, int] = {}

    def progress(stage, _pct):
        stored_at_stage[stage] = len(repo.list_analyses(session, user.id))

    analysis_id = run_pipeline(req, cfg, settings, session, progress, whisper_model=_fake())
    assert stored_at_stage["transcribe"] == 0 and stored_at_stage["coach"] == 1 and stored_at_stage["done"] == 1
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.source_sha256 == "c" * 64 and row.content_sha256 != row.source_sha256


@requires_ffmpeg
def test_pipeline_dedupe_hit_updates_speaker_context(cfg, session, tmp_path: Path):
    req1, user = _req(session, tmp_path, "a.wav")
    req1.speaker_context = "first"
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    first = run_pipeline(req1, cfg, settings, session, lambda s, p: None, whisper_model=_fake())
    job2 = repo.create_job(session, user.id)
    req2 = JobRequest(job_id=job2.id, user_id=user.id, source_path=req1.source_path, file_name="a.wav",
                      recorded_at=req1.recorded_at, speaker_context="investor pitch")
    assert run_pipeline(req2, cfg, settings, session, lambda s, p: None, whisper_model=_fake()) == first
    assert repo.get_analysis(session, user.id, first).speaker_context == "investor pitch"
    job3 = repo.create_job(session, user.id)
    req3 = JobRequest(job_id=job3.id, user_id=user.id, source_path=req1.source_path, file_name="a.wav",
                      recorded_at=req1.recorded_at)  # no context given: keep the stored one
    run_pipeline(req3, cfg, settings, session, lambda s, p: None, whisper_model=_fake())
    assert repo.get_analysis(session, user.id, first).speaker_context == "investor pitch"


@requires_ffmpeg
def test_pipeline_survives_whisper_failure(cfg, session, tmp_path: Path):
    class Broken:
        def transcribe(self, *a, **k):
            raise RuntimeError("model exploded")

    req, user = _req(session, tmp_path)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    analysis_id = run_pipeline(req, cfg, settings, session, lambda s, p: None, whisper_model=Broken())
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.transcript_json is None and row.metrics_json["pitch"] is not None


@requires_ffmpeg
def test_pipeline_bad_audio_raises_clear_error(cfg, session, tmp_path: Path):
    user = repo.upsert_user(session, "sub", None, None)
    job = repo.create_job(session, user.id)
    bad = tmp_path / "not_audio.mp3"
    bad.write_bytes(b"this is not audio")
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=bad, file_name="not_audio.mp3",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    with pytest.raises(Exception) as e:
        run_pipeline(req, cfg, Settings(_env_file=None, data_dir=tmp_path / "data"), session, lambda s, p: None, whisper_model=_fake())
    assert "ffmpeg" in str(e.value).lower() or "audio" in str(e.value).lower()
    assert str(e.value) == "could not decode not_audio.mp3: not a supported audio/video file"
    assert str(tmp_path) not in str(e.value) and "ffprobe" not in str(e.value)


def _llm_enabled_cfg(cfg):
    return cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"enabled": True})})


@requires_ffmpeg
def test_pipeline_runs_coaching_when_llm_enabled(cfg, session, tmp_path: Path):
    req, user = _req(session, tmp_path)
    req.llm_enabled = True
    req.llm_model = "test-model"
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    seen: list[tuple[str, int]] = []
    provider = FakeProvider([VALID_COACHING])
    analysis_id = run_pipeline(req, _llm_enabled_cfg(cfg), settings, session, lambda s, p: seen.append((s, p)),
                               whisper_model=_fake(), llm_provider=provider)
    assert [s for s, _ in seen] == list(STAGES)  # stage sequence is unchanged
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.coaching_json == VALID_COACHING
    assert not row.coaching_warnings


@requires_ffmpeg
def test_pipeline_dedupe_hit_coaches_the_existing_row(cfg, session, tmp_path: Path):
    req1, user = _req(session, tmp_path, "a.wav")
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    first = run_pipeline(req1, cfg, settings, session, lambda s, p: None, whisper_model=_fake())
    assert repo.get_analysis(session, user.id, first).coaching_json is None

    job2 = repo.create_job(session, user.id)
    req2 = JobRequest(job_id=job2.id, user_id=user.id, source_path=req1.source_path, file_name="a.wav",
                      recorded_at=req1.recorded_at, llm_enabled=True, llm_model="test-model")
    provider = FakeProvider([VALID_COACHING])
    second = run_pipeline(req2, _llm_enabled_cfg(cfg), settings, session, lambda s, p: None,
                          whisper_model=_fake(), llm_provider=provider)

    assert second == first
    row = repo.get_analysis(session, user.id, first)
    assert row.coaching_json == VALID_COACHING


@requires_ffmpeg
def test_pipeline_coaching_failure_still_reaches_done(cfg, session, tmp_path: Path):
    req, user = _req(session, tmp_path)
    req.llm_enabled = True
    req.llm_model = "test-model"
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    seen: list[tuple[str, int]] = []
    provider = FakeProvider([LLMError("down")])
    analysis_id = run_pipeline(req, _llm_enabled_cfg(cfg), settings, session, lambda s, p: seen.append((s, p)),
                               whisper_model=_fake(), llm_provider=provider)
    assert seen[-1] == ("done", 100)  # coaching never fails the job
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.coaching_json is None
    assert row.coaching_warnings == ["coaching failed: down"]


@requires_ffmpeg
def test_pipeline_llm_requested_but_disabled_stores_warning(cfg, session, tmp_path: Path):
    req, user = _req(session, tmp_path)
    req.llm_enabled = True
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    disabled_cfg = cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"enabled": False})})
    analysis_id = run_pipeline(req, disabled_cfg, settings, session, lambda s, p: None, whisper_model=_fake())
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.coaching_json is None
    assert row.coaching_warnings == ["coaching is not enabled on this server"]


def _raising_coach(*_a, **_k):
    raise RuntimeError("database is locked")


@requires_ffmpeg
def test_pipeline_coach_stage_exception_still_reaches_done(cfg, session, tmp_path: Path, monkeypatch, caplog):
    monkeypatch.setattr("vocal_coach.pipeline.coach_analysis", _raising_coach)
    req, user = _req(session, tmp_path)
    req.llm_enabled = True
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    seen: list[tuple[str, int]] = []
    with caplog.at_level("WARNING", logger="vocal_coach.pipeline"):
        analysis_id = run_pipeline(req, _llm_enabled_cfg(cfg), settings, session,
                                   lambda s, p: seen.append((s, p)), whisper_model=_fake())
    assert seen[-1] == ("done", 100)
    assert repo.get_analysis(session, user.id, analysis_id) is not None
    assert any(str(req.job_id) in r.getMessage() for r in caplog.records)


@requires_ffmpeg
def test_pipeline_dedupe_coach_stage_exception_still_reaches_done(cfg, session, tmp_path: Path, monkeypatch, caplog):
    req1, user = _req(session, tmp_path, "a.wav")
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    first = run_pipeline(req1, cfg, settings, session, lambda s, p: None, whisper_model=_fake())

    monkeypatch.setattr("vocal_coach.pipeline.coach_analysis", _raising_coach)
    job2 = repo.create_job(session, user.id)
    req2 = JobRequest(job_id=job2.id, user_id=user.id, source_path=req1.source_path, file_name="a.wav",
                      recorded_at=req1.recorded_at, llm_enabled=True, llm_model="test-model")
    seen: list[tuple[str, int]] = []
    with caplog.at_level("WARNING", logger="vocal_coach.pipeline"):
        second = run_pipeline(req2, _llm_enabled_cfg(cfg), settings, session,
                              lambda s, p: seen.append((s, p)), whisper_model=_fake())
    assert second == first
    assert seen[-1] == ("done", 100)
    assert any(str(job2.id) in r.getMessage() for r in caplog.records)


@requires_ffmpeg
def test_pipeline_downloads_drive_file_when_not_cached(cfg, session, tmp_path: Path):
    req, user = _drive_req(session, tmp_path, cached=False)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    calls: list[tuple] = []

    def fake_downloader(sess, s, user_id, file_id, modified_time, dest):
        calls.append((sess, s, user_id, file_id, modified_time, dest))
        synth.write_wav(dest, _speech())
        return dest

    seen: list[tuple[str, int]] = []
    analysis_id = run_pipeline(req, cfg, settings, session, lambda s, p: seen.append((s, p)),
                               whisper_model=_fake(), drive_downloader=fake_downloader)

    assert [s for s, _ in seen] == list(STAGES)  # stage sequence unchanged
    assert len(calls) == 1
    assert calls[0][2:5] == (user.id, "file-1", "2026-10-04T10:42:00.000Z")
    assert calls[0][5] == req.source_path
    row = repo.get_analysis(session, user.id, analysis_id)
    assert row.drive_file_id == "file-1"


@requires_ffmpeg
def test_pipeline_cache_hit_skips_the_drive_downloader(cfg, session, tmp_path: Path):
    req, user = _drive_req(session, tmp_path, cached=True)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")

    def downloader_must_not_be_called(*_a, **_k):
        raise AssertionError("the downloader must not be called on a cache hit")

    analysis_id = run_pipeline(req, cfg, settings, session, lambda s, p: None, whisper_model=_fake(),
                               drive_downloader=downloader_must_not_be_called)

    row = repo.get_analysis(session, user.id, analysis_id)
    assert row is not None and row.drive_file_id == "file-1"


def test_pipeline_drive_not_connected_gives_reconnect_message(cfg, session, tmp_path: Path):
    req, user = _drive_req(session, tmp_path, cached=False)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")

    def failing_downloader(*_a, **_k):
        raise DriveNotConnected("drive_not_connected")

    with pytest.raises(RuntimeError) as exc_info:
        run_pipeline(req, cfg, settings, session, lambda s, p: None, whisper_model=_fake(),
                     drive_downloader=failing_downloader)
    assert "reconnect it in Settings" in str(exc_info.value)


def test_pipeline_drive_not_found_names_the_file(cfg, session, tmp_path: Path):
    req, user = _drive_req(session, tmp_path, cached=False)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")

    def failing_downloader(*_a, **_k):
        raise DriveNotFound("drive file file-1 not found")

    with pytest.raises(RuntimeError) as exc_info:
        run_pipeline(req, cfg, settings, session, lambda s, p: None, whisper_model=_fake(),
                     drive_downloader=failing_downloader)
    assert str(exc_info.value) == "Drive file take.wav was not found"
