import io
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

from tests import synth
from tests.api_fixtures import make_test_app
from vocal_coach.api.analyses import _download_filename, _reject_if_declared_too_large
from vocal_coach.storage import repo
from vocal_coach.storage.db import make_engine, make_session_factory


def fake_job_fn(req, database_url, config_path):
    """Pretend the pipeline ran: store a tiny analysis and finish the job.

    Uses the real byte sha of the uploaded file so dedupe and file cleanup behave as in production.
    """
    import hashlib

    sha = hashlib.sha256(req.source_path.read_bytes()).hexdigest()
    engine = make_engine(database_url)
    with make_session_factory(engine)() as s:
        row = repo.create_analysis(
            s, req.user_id, file_name=req.file_name, drive_file_id=None, content_sha256=sha,
            recorded_at=req.recorded_at, analyser_version="0.1.0", config_hash="sha256:test",
            metrics_json={"pitch": {"f0_median_hz": 123.0, "f0_range_st": 9.0}, "phrasing": {"pauses_per_min": 10.0},
                          "intonation": {"flat_pct": 30.0}, "pace": {"articulation_rate_syl_per_sec": 4.0},
                          "energy": {"trailing_off_count": 2}},
            transcript_json={"derived": {"fillers_per_min": 1.5}, "text": "hi"}, speaker_context=req.speaker_context,
        )
        repo.update_job(s, req.job_id, status="done", stage="done", progress_pct=100, analysis_id=row.id)
    engine.dispose()


def failing_job_fn(req, database_url, config_path):
    engine = make_engine(database_url)
    with make_session_factory(engine)() as s:
        repo.update_job(s, req.job_id, status="failed", error="boom")
    engine.dispose()


def _wav_bytes(seconds=1.0) -> bytes:
    from scipy.io import wavfile
    buf = io.BytesIO()
    wavfile.write(buf, synth.SR, (synth.tone(120, seconds) * 32767).astype("int16"))
    return buf.getvalue()


def _upload(client, headers, name="clip.wav", data=None, **form):
    return client.post("/api/analyses", headers=headers, files={"file": (name, data or _wav_bytes(), "audio/wav")}, data=form)


def test_upload_creates_job_and_analysis_visible_in_list_and_detail(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        r = _upload(client, ctx["auth"](), speaker_context="sales pitch")
        assert r.status_code == 202
        job_id = r.json()["job_ids"][0]
        job = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()
        assert job["status"] == "done" and job["analysis_id"]
        listing = client.get("/api/analyses", headers=ctx["auth"]()).json()
        assert len(listing) == 1 and listing[0]["file_name"] == "clip.wav"
        assert listing[0]["f0_median_hz"] == 123.0 and listing[0]["has_transcript"] is True and listing[0]["has_coaching"] is False
        detail = client.get(f"/api/analyses/{job['analysis_id']}", headers=ctx["auth"]()).json()
        assert detail["metrics"]["pitch"]["f0_range_st"] == 9.0 and detail["speaker_context"] == "sales pitch"
        raw = client.get(f"/api/analyses/{job['analysis_id']}/raw/metrics", headers=ctx["auth"]())
        assert raw.status_code == 200 and raw.headers["content-disposition"].endswith('clip.metrics.json"')
        assert raw.text == json.dumps(detail["metrics"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert client.get(f"/api/analyses/{job['analysis_id']}/raw/coaching", headers=ctx["auth"]()).status_code == 404
        stored = list((tmp_path / "data" / "uploads").rglob("*.wav"))
        assert len(stored) == 1


def test_cross_user_is_404_everywhere(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]("alice")).json()["job_ids"][0]
        analysis_id = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]("alice")).json()["analysis_id"]
        bob = ctx["auth"]("bob")
        assert client.get(f"/api/jobs/{job_id}", headers=bob).status_code == 404
        assert client.get(f"/api/analyses/{analysis_id}", headers=bob).status_code == 404
        assert client.delete(f"/api/analyses/{analysis_id}", headers=bob).status_code == 404
        assert client.get("/api/analyses", headers=bob).json() == []
        assert client.post(f"/api/analyses/{analysis_id}/coach", headers=bob).status_code == 404
        assert client.post(f"/api/analyses/{analysis_id}/coach", headers=ctx["auth"]("alice")).status_code == 501


def test_delete_removes_row_and_upload_file(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        analysis_id = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()["analysis_id"]
        assert list((tmp_path / "data" / "uploads").rglob("*.wav"))
        assert client.delete(f"/api/analyses/{analysis_id}", headers=ctx["auth"]()).status_code == 204
        assert client.get(f"/api/analyses/{analysis_id}", headers=ctx["auth"]()).status_code == 404
        assert not list((tmp_path / "data" / "uploads").rglob("*.wav"))


def test_upload_validation(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn, max_upload_mb=1)
    with TestClient(app) as client:
        assert _upload(client, ctx["auth"](), name="notes.txt", data=b"hello").status_code == 415
        big = b"\0" * (1024 * 1024 + 1)
        r = _upload(client, ctx["auth"](), name="big.mp3", data=big)
        assert r.status_code == 413
        assert not list((tmp_path / "data" / "uploads").rglob("*"))  # partial upload removed
        r = client.post("/api/analyses", headers=ctx["auth"](), json={"source": "drive", "file_ids": ["x"]})
        assert r.status_code == 501
        assert client.post("/api/analyses", files={"file": ("a.wav", b"x", "audio/wav")}).status_code == 401


def test_failed_job_is_visible(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=failing_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        job = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()
        assert job["status"] == "failed" and job["error"] == "boom"


def test_upload_returns_503_and_fails_job_when_runner_unavailable(tmp_path):
    from vocal_coach.jobs.runner import RunnerUnavailable

    class DeadRunner:
        def submit(self, req):
            raise RunnerUnavailable("job runner unavailable")

    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        app.state.runner = DeadRunner()
        r = _upload(client, ctx["auth"]())
        assert r.status_code == 503 and r.json()["detail"] == "job runner unavailable; try again"
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "user-1", None, None)
            jobs = repo.list_jobs(s, user.id)
        assert len(jobs) == 1 and (jobs[0].status, jobs[0].error) == ("failed", "job runner unavailable")


def test_list_pagination(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        for i in range(3):
            _upload(client, ctx["auth"](), name=f"c{i}.wav", data=_wav_bytes(1.0 + 0.1 * i))
        assert len(client.get("/api/analyses?limit=2", headers=ctx["auth"]()).json()) == 2
        assert len(client.get("/api/analyses?limit=2&offset=2", headers=ctx["auth"]()).json()) == 1
        assert client.get("/api/analyses?limit=0", headers=ctx["auth"]()).status_code == 422


def test_download_filename_sanitises_quotes_and_crlf():
    assert _download_filename('evil"na\r\nme', "metrics") == "evil_na__me.metrics.json"


def test_download_filename_empty_stem_falls_back_to_analysis():
    assert _download_filename("", "transcript") == "analysis.transcript.json"


def test_download_filename_is_truncated():
    assert _download_filename("a" * 500, "coaching") == ("a" * 100) + ".coaching.json"


def test_raw_download_filename_header_has_no_injected_quote_or_crlf(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"](), name='we ird"name.wav').json()["job_ids"][0]
        analysis_id = client.get(f"/api/jobs/{job_id}", headers=ctx["auth"]()).json()["analysis_id"]
        raw = client.get(f"/api/analyses/{analysis_id}/raw/metrics", headers=ctx["auth"]())
        assert raw.status_code == 200
        cd = raw.headers["content-disposition"]
        assert cd.count('"') == 2  # only the two delimiters around the filename value
        filename_value = cd.split('filename="', 1)[1].rstrip('"')
        assert '"' not in filename_value and "\r" not in filename_value and "\n" not in filename_value


def test_reject_if_declared_too_large_raises_413_without_reading_body():
    req = StarletteRequest({"type": "http", "headers": [(b"content-length", b"999999999")]})
    with pytest.raises(HTTPException) as exc_info:
        _reject_if_declared_too_large(req, max_bytes=1000)
    assert exc_info.value.status_code == 413


def test_reject_if_declared_too_large_ignores_non_numeric_header():
    req = StarletteRequest({"type": "http", "headers": [(b"content-length", b"not-a-number")]})
    _reject_if_declared_too_large(req, max_bytes=1000)  # must not raise


def test_reject_if_declared_too_large_ignores_missing_header():
    req = StarletteRequest({"type": "http", "headers": []})
    _reject_if_declared_too_large(req, max_bytes=1000)  # must not raise
