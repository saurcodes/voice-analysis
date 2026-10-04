# Vocal Coach — Plan 4: FastAPI, Keycloak Auth, Jobs, Compose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running backend: Keycloak-authenticated FastAPI serving upload → background analysis+transcription job → stored analysis, with job progress over SSE, per-user Library/detail/compare endpoints, and a docker-compose stack (Postgres, Keycloak, backend).

**Architecture:** `vocal_coach/main.py` is an app factory with everything injectable (engine, job runner, JWKS fetcher) so tests run on SQLite with a synchronous fake runner. `pipeline.py` runs one job end to end: extract → analyse → transcribe → store, computing `Tracks` once and sharing it. `jobs/runner.py` wraps a `ProcessPoolExecutor` (spawn) because praat-parselmouth and CTranslate2 are not safe to share across threads; each worker process opens its own DB session and writes `jobs` progress directly, so the SSE endpoint only has to poll the row. `auth/` verifies Keycloak RS256 tokens against a cached JWKS and upserts the user. Drive and LLM endpoints are stubs returning 501/`enabled: false` until Plans 6–7.

**Tech Stack:** FastAPI, uvicorn, python-multipart, sse-starlette, PyJWT[crypto], httpx (JWKS fetch + TestClient), SQLAlchemy/Alembic (Plan 3), docker compose, Keycloak 26, Postgres 16.

**Spec:** `docs/superpowers/specs/2026-10-03-vocal-coach-design.md` — §3 (layout), §4 (auth), §10 (jobs), §12 (API), §14 (deployment), §15 (errors), §16 rows `test_auth`, `test_jobs`, `test_api_analyses`.

## Global Constraints

- Python ≥ 3.11; package `backend/vocal_coach`; tests `backend/tests`; run from `backend/` with `.venv`.
- Auth per spec §4: RS256 JWT, signature against Keycloak JWKS (cached, refreshed on unknown `kid`), `iss == KEYCLOAK_ISSUER`, `aud` contains `KEYCLOAK_AUDIENCE`, `exp` enforced; `sub`, `email`, `preferred_username` extracted; first sight upserts `users`. Invalid/missing token → 401. Cross-user access by id → 404 (never 403).
- Jobs per spec §10: stages `download → extract → analyse → transcribe → coach → done`; progress written to the `jobs` row; SSE polls every 500 ms emitting `stage`, `progress`, `done {analysis_id}`, `error {message}` and closes on done/failed; on startup `queued|running` jobs → `failed` with error `"server restarted"`; one job per file.
- Errors per spec §15: 401 auth; 413 upload too large (`MAX_UPLOAD_MB`, default 500); 415 wrong type (allowed `m4a mp3 wav mov mp4`); job crash → `failed` with error; missing ffmpeg → refuse to start.
- Dedupe: same user + same `content_sha256` + same `config_hash` + same `analyser_version` → existing analysis returned, job completes immediately (Plan 3 unique key).
- Settings from env/`.env` via pydantic-settings: `DATABASE_URL`, `KEYCLOAK_ISSUER`, `KEYCLOAK_AUDIENCE`, `FRONTEND_ORIGIN`, `DATA_DIR`, `JOB_WORKERS`, `MAX_UPLOAD_MB`.
- `analyse_wav` output must be byte-identical whether or not a precomputed `Tracks` is passed (determinism test still passes).
- Test output pristine under `pytest -v -W error`. Commit after every task; messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **Token with `aud: account` only** (Keycloak default when no audience mapper): must be rejected with 401, and the realm export must include an audience mapper so real tokens pass. Test in Task 2; realm in Task 7.
2. **Upload of a 0-byte or non-audio file with an allowed extension** (renamed .txt → .mp3): ffmpeg fails in the worker → job `failed` with a readable error, never a hung `running` job. Test in Task 4.
3. **Second upload of the same file while the first job is still running**: second job must also complete (dedupe returns the existing row, or the unique-constraint race resolves to the existing row) — never a stuck job. Test in Task 1 (pipeline) and Task 5 (API).
4. **SSE client connects after the job already finished**: stream must emit the terminal event immediately and close, not hang. Test in Task 6.
5. **Backend restart with a job mid-flight**: the row reads `failed / server restarted` and the Library can show it. Test in Task 3 (lifespan).

---

### Task 1: Settings, dependencies, shared-Tracks analyser, pipeline

**Files:**
- Modify: `backend/pyproject.toml` (deps: `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `python-multipart>=0.0.9`, `sse-starlette>=2.1`, `PyJWT[crypto]>=2.9`, `httpx>=0.27`)
- Modify: `backend/requirements.lock` (regenerate; Plan 1 pins unchanged)
- Modify: `backend/vocal_coach/settings.py`
- Modify: `backend/vocal_coach/analysis/analyser.py` (`analyse_wav(..., tracks=None)`)
- Create: `backend/vocal_coach/pipeline.py`
- Test: `backend/tests/test_settings.py` (extend), `backend/tests/test_analyser.py` (extend), `backend/tests/test_pipeline.py`

**Interfaces:**
- Produces (`settings.py`): `Settings` gains `keycloak_issuer: str = "http://localhost:8080/realms/vocal-coach"`, `keycloak_audience: str = "vocal-coach-web"`, `frontend_origin: str = "http://localhost:5173"`, `data_dir: Path = Path("data")`, `job_workers: int = 1`, `max_upload_mb: int = 500`, `require_ffmpeg: bool = True`, property `jwks_url -> str` (`f"{keycloak_issuer}/protocol/openid-connect/certs"`), property `max_upload_bytes -> int`.
- Produces (`analyser.py`): `analyse_wav(wav_path: Path, cfg: AppConfig, source: SourceInfo, tracks: Tracks | None = None) -> MetricsReport` — when `tracks` is given, no `parselmouth.Sound`/`extract_tracks` call happens.
- Produces (`pipeline.py`): `STAGES = ("download", "extract", "analyse", "transcribe", "coach", "done")`; `STAGE_PROGRESS: dict[str, int]` (`download 5, extract 20, analyse 55, transcribe 85, coach 90, done 100`); `@dataclass class JobRequest`: `job_id: uuid.UUID`, `user_id: uuid.UUID`, `source_path: Path`, `file_name: str`, `recorded_at: datetime`, `drive_file_id: str | None = None`, `drive_modified_time: str | None = None`, `speaker_context: str | None = None`, `llm_enabled: bool = False`, `llm_model: str | None = None`; `Progress = Callable[[str, int], None]`; `run_pipeline(req: JobRequest, cfg: AppConfig, settings: Settings, session: Session, progress: Progress, *, whisper_model: WhisperLike | None = None) -> uuid.UUID` (returns the analysis id; work dir `settings.data_dir / "work" / str(job_id)` created and removed).

- [ ] **Step 1: Dependencies**

Add the six packages to `pyproject.toml` dependencies; `pip install -e ".[dev]" && pip freeze | grep -v '^-e' > requirements.lock`; confirm `git diff requirements.lock | grep -E '^[-+](praat|numpy|scipy)'` prints nothing.

- [ ] **Step 2: Failing tests**

Append to `backend/tests/test_settings.py`:

```python
def test_new_settings_defaults_and_derived(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.keycloak_issuer == "http://localhost:8080/realms/vocal-coach"
    assert s.keycloak_audience == "vocal-coach-web"
    assert s.jwks_url == "http://localhost:8080/realms/vocal-coach/protocol/openid-connect/certs"
    assert s.job_workers == 1 and s.max_upload_mb == 500 and s.require_ffmpeg is True
    assert s.max_upload_bytes == 500 * 1024 * 1024
    assert str(s.data_dir) == "data"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_ISSUER", "https://kc.example/realms/x")
    monkeypatch.setenv("JOB_WORKERS", "3")
    monkeypatch.setenv("DATA_DIR", "/srv/data")
    s = get_settings()
    assert s.jwks_url == "https://kc.example/realms/x/protocol/openid-connect/certs"
    assert s.job_workers == 3 and str(s.data_dir) == "/srv/data"
    monkeypatch.setenv("KEYCLOAK_JWKS_URL_OVERRIDE", "http://keycloak:8080/realms/x/protocol/openid-connect/certs")
    assert get_settings().jwks_url == "http://keycloak:8080/realms/x/protocol/openid-connect/certs"
```

Append to `backend/tests/test_analyser.py`:

```python
def test_analyse_wav_with_precomputed_tracks_is_identical(cfg, tmp_path: Path, monkeypatch):
    import parselmouth
    from vocal_coach.analysis import analyser as mod
    from vocal_coach.analysis.tracks import extract_tracks

    wav = synth.write_wav(tmp_path / "s.wav", _speechlike())
    src = _source(wav, 10.8)
    baseline = to_canonical_json(analyse_wav(wav, cfg, src))
    tracks = extract_tracks(parselmouth.Sound(str(wav)), cfg.analysis)

    def boom(*a, **k):  # analyse_wav must not re-extract when tracks are supplied
        raise AssertionError("extract_tracks called despite precomputed tracks")

    monkeypatch.setattr(mod, "extract_tracks", boom)
    assert to_canonical_json(analyse_wav(wav, cfg, src, tracks=tracks)) == baseline
```

`backend/tests/test_pipeline.py`:

```python
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests import synth
from tests.conftest import requires_ffmpeg
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.pipeline import STAGES, JobRequest, run_pipeline
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.storage.db import create_all, make_engine, make_session_factory


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
    assert seen == ["download", "extract", "done"]  # no analyse/transcribe on a dedupe hit


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_settings.py tests/test_analyser.py tests/test_pipeline.py -v`
Expected: new tests FAIL (`AttributeError` on settings fields, `TypeError` unexpected kwarg `tracks`, `ModuleNotFoundError: vocal_coach.pipeline`).

- [ ] **Step 4: Implement**

`backend/vocal_coach/settings.py`:

```python
"""Process-level settings from environment / .env (not from config.yaml)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BYTES_PER_MB = 1024 * 1024
JWKS_PATH = "/protocol/openid-connect/certs"  # Keycloak OIDC JWKS endpoint, relative to the realm issuer


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach"
    keycloak_issuer: str = "http://localhost:8080/realms/vocal-coach"
    keycloak_audience: str = "vocal-coach-web"
    # In compose the browser sees Keycloak at localhost:8080 (the issuer) but the backend container
    # must fetch JWKS via the compose network; this override points only the fetch elsewhere.
    keycloak_jwks_url_override: str | None = None
    frontend_origin: str = "http://localhost:5173"
    data_dir: Path = Path("data")
    job_workers: int = 1
    max_upload_mb: int = 500
    require_ffmpeg: bool = True

    @property
    def jwks_url(self) -> str:
        return self.keycloak_jwks_url_override or (self.keycloak_issuer.rstrip("/") + JWKS_PATH)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * BYTES_PER_MB


def get_settings() -> Settings:
    return Settings()
```

`analyser.py`: change the signature to `analyse_wav(wav_path, cfg, source, tracks=None)`. Inside, if `tracks is None`: keep the current code (`sound = parselmouth.Sound(str(wav_path))`, min-duration guard on `sound.get_total_duration()`, `tracks = extract_tracks(sound, cfg.analysis)`); else use `tracks.duration_s` for the min-duration guard and skip extraction. Everything downstream already uses `tracks`.

`backend/vocal_coach/pipeline.py`:

```python
"""One analysis job end to end: extract → analyse → transcribe → (coach) → store.

Runs inside a job worker. Computes `Tracks` once and shares it between analysis and
transcription so both see identical samples. Dedupe: if this user already has an analysis
for the same WAV bytes, config and analyser version, return it without re-analysing.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import parselmouth
from sqlalchemy.orm import Session

from vocal_coach.analysis.analyser import ANALYSER_VERSION, analyse_wav
from vocal_coach.analysis.audio import extract_wav
from vocal_coach.analysis.schema import SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.config import AppConfig, config_hash
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.transcription.run import transcribe_file
from vocal_coach.transcription.transcriber import WhisperLike, get_model

import json

log = logging.getLogger(__name__)

STAGES = ("download", "extract", "analyse", "transcribe", "coach", "done")
STAGE_PROGRESS = {"download": 5, "extract": 20, "analyse": 55, "transcribe": 85, "coach": 90, "done": 100}
WORK_SUBDIR = "work"  # DATA_DIR/work/<job_id>/ holds the extracted WAV for the job's lifetime

Progress = Callable[[str, int], None]


@dataclass
class JobRequest:
    job_id: uuid.UUID
    user_id: uuid.UUID
    source_path: Path
    file_name: str
    recorded_at: datetime
    drive_file_id: str | None = None
    drive_modified_time: str | None = None
    speaker_context: str | None = None
    llm_enabled: bool = False
    llm_model: str | None = None


def _as_dict(model) -> dict:
    return json.loads(to_canonical_json(model))


def run_pipeline(
    req: JobRequest, cfg: AppConfig, settings: Settings, session: Session, progress: Progress,
    *, whisper_model: WhisperLike | None = None,
) -> uuid.UUID:
    work = settings.data_dir / WORK_SUBDIR / str(req.job_id)
    work.mkdir(parents=True, exist_ok=True)
    try:
        progress("download", STAGE_PROGRESS["download"])  # source is already local (upload); Drive arrives in Plan 7
        wav = work / (Path(req.file_name).stem + ".wav")
        try:
            info = extract_wav(req.source_path, wav)
        except (subprocess.CalledProcessError, ValueError) as e:  # not audio, truncated, or no audio stream
            raise RuntimeError(f"ffmpeg could not decode {req.file_name}: {e}") from e
        progress("extract", STAGE_PROGRESS["extract"])

        existing = repo.find_analysis(session, req.user_id, info.content_sha256, config_hash(cfg), ANALYSER_VERSION)
        if existing is not None:
            progress("done", STAGE_PROGRESS["done"])
            return existing.id

        tracks = extract_tracks(parselmouth.Sound(str(wav)), cfg.analysis)
        source = SourceInfo(
            file_name=req.file_name, drive_file_id=req.drive_file_id, drive_modified_time=req.drive_modified_time,
            content_sha256=info.content_sha256, duration_s=info.duration_s,
            original_channels=info.original_channels, original_sample_rate=info.original_sample_rate,
        )
        report = analyse_wav(wav, cfg, source, tracks=tracks)
        progress("analyse", STAGE_PROGRESS["analyse"])

        transcript_json: dict | None
        try:
            model = whisper_model if whisper_model is not None else get_model(cfg.transcription)
            transcript_json = _as_dict(transcribe_file(wav, cfg, model=model, tracks=tracks))
        except Exception:  # spec §15: transcription failure degrades, it does not fail the job
            log.exception("transcription failed for job %s; storing analysis without transcript", req.job_id)
            transcript_json = None
        progress("transcribe", STAGE_PROGRESS["transcribe"])

        progress("coach", STAGE_PROGRESS["coach"])  # LLM coaching lands in Plan 6

        row = repo.create_analysis(
            session, req.user_id, file_name=req.file_name, drive_file_id=req.drive_file_id,
            content_sha256=info.content_sha256, recorded_at=req.recorded_at,
            analyser_version=report.analyser_version, config_hash=report.config_hash,
            metrics_json=_as_dict(report), transcript_json=transcript_json, speaker_context=req.speaker_context,
        )
        progress("done", STAGE_PROGRESS["done"])
        return row.id
    finally:
        shutil.rmtree(work, ignore_errors=True)
```

(`import subprocess` at the top of `pipeline.py`.)

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_settings.py tests/test_analyser.py tests/test_pipeline.py tests/test_determinism.py -v -W error`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/requirements.lock backend/vocal_coach/settings.py backend/vocal_coach/analysis/analyser.py backend/vocal_coach/pipeline.py backend/tests/test_settings.py backend/tests/test_analyser.py backend/tests/test_pipeline.py
git commit -m "feat(api): settings, shared-Tracks analyser, end-to-end job pipeline

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Keycloak JWT verification and current-user dependency

**Files:**
- Create: `backend/vocal_coach/auth/__init__.py` (empty)
- Create: `backend/vocal_coach/auth/jwt.py`
- Create: `backend/vocal_coach/auth/deps.py`
- Create: `backend/tests/auth_keys.py`
- Create: `backend/tests/test_auth.py`

**Interfaces:**
- Produces (`jwt.py`): `class AuthError(Exception)`; `class JWKSCache`: `__init__(self, url: str, fetch: Callable[[str], dict] | None = None, min_refresh_interval_s: float = 60.0)`, `key_for(kid: str) -> PyJWK` (refetches once on unknown kid, rate-limited), `refresh()`; `verify_token(token: str, *, issuer: str, audience: str, jwks: JWKSCache) -> dict` (claims; raises `AuthError`); `fetch_jwks(url) -> dict` (httpx GET).
- Produces (`deps.py`): `@dataclass class CurrentUser: id: uuid.UUID; sub: str; email: str | None; username: str | None`; `get_current_user(request: Request, credentials = Depends(HTTPBearer(auto_error=False)), session = Depends(get_session)) -> CurrentUser` — reads `request.app.state.settings` and `request.app.state.jwks`, verifies, `repo.upsert_user`, returns `CurrentUser`. Raises `HTTPException(401)` on any `AuthError` or missing header.
- Produces (`tests/auth_keys.py`): `make_rsa_jwks() -> tuple[private_pem: bytes, jwks: dict, kid: str]`; `mint(private_pem, kid, *, iss, aud, sub="user-1", email="u@x.test", username="user1", exp_delta_s=600, extra: dict | None = None) -> str`.

- [ ] **Step 1: Test helpers and failing tests**

`backend/tests/auth_keys.py`:

```python
"""RSA test keys and token minting for auth tests. Never used in production."""
from __future__ import annotations

import base64
import time
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url(n: int, length: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()


def make_rsa_jwks() -> tuple[bytes, dict, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_numbers()
    kid = uuid.uuid4().hex
    jwks = {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
                      "n": _b64url(pub.n, 256), "e": _b64url(pub.e, 3)}]}
    return pem, jwks, kid


def mint(private_pem: bytes, kid: str, *, iss: str, aud, sub="user-1", email="u@x.test", username="user1",
         exp_delta_s: int = 600, extra: dict | None = None) -> str:
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "sub": sub, "email": email, "preferred_username": username,
              "iat": now, "exp": now + exp_delta_s, "azp": "vocal-coach-web"}
    claims.update(extra or {})
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})
```

`backend/tests/test_auth.py`:

```python
import pytest

from tests.auth_keys import make_rsa_jwks, mint
from vocal_coach.auth.jwt import AuthError, JWKSCache, verify_token

ISS = "http://kc.test/realms/vocal-coach"
AUD = "vocal-coach-web"


@pytest.fixture
def keys():
    pem, jwks, kid = make_rsa_jwks()
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        return jwks

    return pem, kid, JWKSCache("http://kc.test/jwks", fetch=fetch, min_refresh_interval_s=0.0), calls


def test_valid_token_returns_claims(keys):
    pem, kid, cache, _ = keys
    claims = verify_token(mint(pem, kid, iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    assert claims["sub"] == "user-1" and claims["preferred_username"] == "user1"


def test_audience_list_containing_target_is_accepted(keys):
    pem, kid, cache, _ = keys
    claims = verify_token(mint(pem, kid, iss=ISS, aud=["account", AUD]), issuer=ISS, audience=AUD, jwks=cache)
    assert claims["sub"] == "user-1"


def test_account_only_audience_is_rejected(keys):
    pem, kid, cache, _ = keys
    with pytest.raises(AuthError):
        verify_token(mint(pem, kid, iss=ISS, aud="account"), issuer=ISS, audience=AUD, jwks=cache)


def test_expired_wrong_issuer_bad_signature(keys):
    pem, kid, cache, _ = keys
    with pytest.raises(AuthError):
        verify_token(mint(pem, kid, iss=ISS, aud=AUD, exp_delta_s=-10), issuer=ISS, audience=AUD, jwks=cache)
    with pytest.raises(AuthError):
        verify_token(mint(pem, kid, iss="http://other/realms/x", aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    other_pem, _, _ = make_rsa_jwks()
    with pytest.raises(AuthError):
        verify_token(mint(other_pem, kid, iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)


def test_unknown_kid_triggers_one_refetch_then_fails(keys):
    pem, kid, cache, calls = keys
    verify_token(mint(pem, kid, iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    n0 = calls["n"]
    with pytest.raises(AuthError):
        verify_token(mint(pem, "missing-kid", iss=ISS, aud=AUD), issuer=ISS, audience=AUD, jwks=cache)
    assert calls["n"] == n0 + 1


def test_garbage_token_is_auth_error(keys):
    _, _, cache, _ = keys
    with pytest.raises(AuthError):
        verify_token("not.a.jwt", issuer=ISS, audience=AUD, jwks=cache)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.auth'`

- [ ] **Step 3: Implement**

`backend/vocal_coach/auth/jwt.py`:

```python
"""Keycloak access-token verification against a cached JWKS."""
from __future__ import annotations

import threading
import time
from typing import Callable

import httpx
import jwt
from jwt import PyJWK

ALGORITHMS = ["RS256"]  # Keycloak signs access tokens with RS256 by default
JWKS_HTTP_TIMEOUT_S = 5.0
DEFAULT_MIN_REFRESH_INTERVAL_S = 60.0  # an attacker cannot make us hammer Keycloak with unknown kids


class AuthError(Exception):
    pass


def fetch_jwks(url: str) -> dict:
    response = httpx.get(url, timeout=JWKS_HTTP_TIMEOUT_S)
    response.raise_for_status()
    return response.json()


class JWKSCache:
    def __init__(self, url: str, fetch: Callable[[str], dict] | None = None,
                 min_refresh_interval_s: float = DEFAULT_MIN_REFRESH_INTERVAL_S):
        self._url = url
        self._fetch = fetch or fetch_jwks
        self._min_interval = min_refresh_interval_s
        self._keys: dict[str, PyJWK] = {}
        self._last_refresh = 0.0
        self._lock = threading.Lock()

    def refresh(self) -> None:
        with self._lock:
            data = self._fetch(self._url)
            self._keys = {k["kid"]: PyJWK(k) for k in data.get("keys", []) if "kid" in k}
            self._last_refresh = time.monotonic()

    def key_for(self, kid: str) -> PyJWK:
        if kid not in self._keys and (time.monotonic() - self._last_refresh) >= self._min_interval:
            self.refresh()
        try:
            return self._keys[kid]
        except KeyError:
            raise AuthError(f"unknown signing key {kid!r}") from None


def verify_token(token: str, *, issuer: str, audience: str, jwks: JWKSCache) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        key = jwks.key_for(header.get("kid", ""))
        return jwt.decode(
            token, key=key.key, algorithms=ALGORITHMS, audience=audience, issuer=issuer,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except AuthError:
        raise
    except jwt.PyJWTError as e:
        raise AuthError(str(e)) from e
    except Exception as e:  # malformed header etc.
        raise AuthError(f"invalid token: {e}") from e
```

`backend/vocal_coach/auth/deps.py`:

```python
"""FastAPI dependencies: database session and the authenticated current user."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from vocal_coach.auth.jwt import AuthError, verify_token
from vocal_coach.storage import repo

bearer = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


@dataclass
class CurrentUser:
    id: uuid.UUID
    sub: str
    email: str | None
    username: str | None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    settings = request.app.state.settings
    try:
        claims = verify_token(credentials.credentials, issuer=settings.keycloak_issuer,
                              audience=settings.keycloak_audience, jwks=request.app.state.jwks)
    except AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}", headers={"WWW-Authenticate": "Bearer"})
    user = repo.upsert_user(session, claims["sub"], claims.get("email"), claims.get("preferred_username"))
    return CurrentUser(id=user.id, sub=user.keycloak_sub, email=user.email, username=user.username)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_auth.py -v -W error`
Expected: 6 passed. (`deps.py` is exercised through the app in Task 3.)

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/auth backend/tests/auth_keys.py backend/tests/test_auth.py
git commit -m "feat(auth): Keycloak JWT verification with cached JWKS and current-user dependency

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: App factory, lifespan, `/me`, `/config/public`, `/llm/models` stub

**Files:**
- Create: `backend/vocal_coach/main.py`
- Create: `backend/vocal_coach/api/__init__.py` (empty)
- Create: `backend/vocal_coach/api/me.py`
- Create: `backend/vocal_coach/api/config_public.py`
- Create: `backend/vocal_coach/api/llm.py`
- Create: `backend/vocal_coach/api/jobs.py` (`GET /jobs/{id}` now; SSE added in Task 6)
- Create: `backend/vocal_coach/api/analyses.py` (empty `router = APIRouter()`; filled in Task 5)
- Create: `backend/vocal_coach/api/comparisons.py` (empty `router = APIRouter()`; filled in Task 6)
- Create: `backend/vocal_coach/jobs/__init__.py` (empty)
- Create: `backend/vocal_coach/jobs/runner.py` (interface + sync executor only; the process pool arrives in Task 4)
- Create: `backend/tests/api_fixtures.py`
- Create: `backend/tests/test_app.py`

**Interfaces:**
- Produces (`jobs/runner.py`, part 1): `class SyncExecutor` (`submit(fn, *args, **kwargs)` runs immediately, returns a completed `concurrent.futures.Future`); `class JobRunner`: `__init__(self, settings: Settings, cfg: AppConfig, *, executor=None, job_fn=None)`; `start()`, `stop()`, `submit(req: JobRequest) -> Future`. In this task `start()` only sets `self._executor = executor` (or raises if None — the real pool comes in Task 4); `job_fn` is called as `job_fn(req, database_url: str, config_path: str | None)`.
- Produces (`main.py`): `create_app(settings: Settings | None = None, cfg: AppConfig | None = None, *, engine: Engine | None = None, runner: JobRunner | None = None, jwks: JWKSCache | None = None, run_migrations: bool = True) -> FastAPI`; module-level `app = create_app()` guarded so importing in tests does not connect (`if __name__ != "__main__"` is NOT enough — use a lazy module attribute: define `def _default_app(): return create_app()` and in the Dockerfile/entrypoint run `uvicorn "vocal_coach.main:create_app" --factory`). App state: `settings, cfg, engine, session_factory, runner, jwks, started_at`. Lifespan: `check_ffmpeg()` if `settings.require_ffmpeg`; `upgrade_to_head(settings.database_url)` if `run_migrations and engine is None`; `fail_stale_jobs`; `runner.start()`; on shutdown `runner.stop()`. CORS for `settings.frontend_origin`. Routers mounted under `/api`. `AuthError` → 401.
- Produces (`api/me.py`): `GET /api/me` → `MeResponse(id, email, username, drive_connected: bool, llm_enabled: bool, llm_provider: str | None)`.
- Produces (`api/config_public.py`): `GET /api/config/public` → `{analysis: {...}, articulation: {...}, clarity: {...}, comparison: {...}}` (model dumps; no secrets).
- Produces (`api/llm.py`): `GET /api/llm/models` → `{"enabled": false, "provider": null, "models": []}` until Plan 6; `POST /api/analyses/{id}/coach` → 501 `{"detail": "coaching is not available yet"}` (requires auth, 404 for a foreign/missing id first).
- Produces (`tests/api_fixtures.py`): `make_test_app(tmp_path, *, job_fn=None, max_upload_mb=500) -> tuple[FastAPI, dict]` building a SQLite-file-backed app (`sqlite+pysqlite:///{tmp_path}/t.db`, `create_all`, `run_migrations=False`, `require_ffmpeg=False`, `JobRunner(executor=SyncExecutor(), job_fn=job_fn)`, `JWKSCache(fetch=lambda url: jwks)`); returns the app and a `ctx` dict with `pem, kid, iss, aud, token(sub="user-1", **kw) -> str`, `auth(sub) -> dict headers`, `session_factory`.

- [ ] **Step 1: Fixtures and failing tests**

`backend/tests/api_fixtures.py`:

```python
"""Build a fully wired FastAPI app on SQLite with a synchronous fake job runner."""
from __future__ import annotations

from pathlib import Path

from tests.auth_keys import make_rsa_jwks, mint
from vocal_coach.auth.jwt import JWKSCache
from vocal_coach.config import load_config
from vocal_coach.jobs.runner import JobRunner, SyncExecutor
from vocal_coach.main import create_app
from vocal_coach.settings import Settings
from vocal_coach.storage.db import create_all, make_engine, make_session_factory

ISS = "http://kc.test/realms/vocal-coach"
AUD = "vocal-coach-web"


def make_test_app(tmp_path: Path, *, job_fn=None, max_upload_mb: int = 500):
    pem, jwks, kid = make_rsa_jwks()
    settings = Settings(_env_file=None, database_url=f"sqlite+pysqlite:///{tmp_path / 't.db'}",
                        keycloak_issuer=ISS, keycloak_audience=AUD, data_dir=tmp_path / "data",
                        max_upload_mb=max_upload_mb, require_ffmpeg=False, job_workers=1)
    cfg = load_config()
    engine = make_engine(settings.database_url)
    create_all(engine)
    runner = JobRunner(settings, cfg, executor=SyncExecutor(), job_fn=job_fn)
    app = create_app(settings, cfg, engine=engine, runner=runner,
                     jwks=JWKSCache(settings.jwks_url, fetch=lambda url: jwks, min_refresh_interval_s=0.0),
                     run_migrations=False)
    ctx = {
        "pem": pem, "kid": kid, "iss": ISS, "aud": AUD, "settings": settings, "cfg": cfg,
        "session_factory": make_session_factory(engine),
        "token": lambda sub="user-1", **kw: mint(pem, kid, iss=ISS, aud=AUD, sub=sub, **kw),
    }
    ctx["auth"] = lambda sub="user-1": {"Authorization": f"Bearer {ctx['token'](sub)}"}
    return app, ctx
```

`backend/tests/test_app.py`:

```python
from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.auth_keys import mint
from vocal_coach.storage import repo


def test_me_requires_auth_and_upserts_user(tmp_path):
    app, ctx = make_test_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401
        r = client.get("/api/me", headers=ctx["auth"]("sub-42"))
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == "user1" and body["drive_connected"] is False
        assert body["llm_enabled"] is True and body["llm_provider"] == "openai_compatible"
        with ctx["session_factory"]() as s:
            user = repo.upsert_user(s, "sub-42", None, None)  # already exists; id stable
            assert str(user.id) == body["id"]


def test_account_only_audience_rejected_at_api(tmp_path):
    app, ctx = make_test_app(tmp_path)
    with TestClient(app) as client:
        token = mint(ctx["pem"], ctx["kid"], iss=ctx["iss"], aud="account")
        assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_config_public_and_llm_stub(tmp_path):
    app, ctx = make_test_app(tmp_path)
    with TestClient(app) as client:
        r = client.get("/api/config/public", headers=ctx["auth"]())
        assert r.status_code == 200
        assert r.json()["comparison"]["directions"]["pitch.f0_range_st"] == "up_good"
        assert r.json()["analysis"]["intonation_threshold_st"] == 1.5
        r = client.get("/api/llm/models", headers=ctx["auth"]())
        assert r.status_code == 200 and r.json() == {"enabled": False, "provider": None, "models": []}


def test_lifespan_fails_stale_jobs(tmp_path):
    app, ctx = make_test_app(tmp_path)
    with ctx["session_factory"]() as s:
        user = repo.upsert_user(s, "sub-1", None, None)
        stale = repo.create_job(s, user.id)
        repo.update_job(s, stale.id, status="running", stage="analyse", progress_pct=55)
    with TestClient(app) as client:
        r = client.get(f"/api/jobs/{stale.id}", headers=ctx["auth"]("sub-1"))
        assert r.status_code == 200
        assert r.json()["status"] == "failed" and r.json()["error"] == "server restarted"


def test_cors_allows_frontend_origin(tmp_path):
    app, ctx = make_test_app(tmp_path)
    with TestClient(app) as client:
        r = client.options("/api/me", headers={"Origin": ctx["settings"].frontend_origin,
                                               "Access-Control-Request-Method": "GET"})
        assert r.headers.get("access-control-allow-origin") == ctx["settings"].frontend_origin
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.main'`

- [ ] **Step 3: Implement**

`backend/vocal_coach/jobs/runner.py` (part 1):

```python
"""Job runner: hands JobRequests to an executor. Production uses a process pool (Task 4)."""
from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import Any, Callable, Protocol

from vocal_coach.config import AppConfig
from vocal_coach.pipeline import JobRequest
from vocal_coach.settings import Settings

log = logging.getLogger(__name__)

JobFn = Callable[[JobRequest, str, str | None], None]  # (request, database_url, config_path)


class ExecutorLike(Protocol):
    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future: ...
    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None: ...


class SyncExecutor:
    """Runs the callable immediately in the calling thread. Tests only."""

    def submit(self, fn, /, *args, **kwargs) -> Future:
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except BaseException as e:  # the fake job must surface failures like the real pool would
            fut.set_exception(e)
        return fut

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        return None


class JobRunner:
    def __init__(self, settings: Settings, cfg: AppConfig, *, executor: ExecutorLike | None = None,
                 job_fn: JobFn | None = None, config_path: str | None = None):
        self._settings = settings
        self._cfg = cfg
        self._executor = executor
        self._job_fn = job_fn
        self._config_path = config_path

    def start(self) -> None:
        if self._executor is None:
            raise RuntimeError("no executor configured; the process pool is wired in jobs.runner.make_process_runner")
        if self._job_fn is None:
            raise RuntimeError("no job function configured")

    def stop(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, req: JobRequest) -> Future:
        assert self._executor is not None and self._job_fn is not None
        return self._executor.submit(self._job_fn, req, self._settings.database_url, self._config_path)
```

`backend/vocal_coach/main.py`:

```python
"""FastAPI application factory. Everything heavy is injectable for tests."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from vocal_coach.analysis.audio import check_ffmpeg
from vocal_coach.api import analyses, comparisons, config_public, jobs, llm, me
from vocal_coach.auth.jwt import AuthError, JWKSCache
from vocal_coach.config import AppConfig, load_config
from vocal_coach.jobs.runner import JobRunner
from vocal_coach.settings import Settings, get_settings
from vocal_coach.storage import repo
from vocal_coach.storage.db import make_engine, make_session_factory
from vocal_coach.storage.migrate import upgrade_to_head

log = logging.getLogger(__name__)
API_PREFIX = "/api"


def create_app(
    settings: Settings | None = None, cfg: AppConfig | None = None, *,
    engine: Engine | None = None, runner: JobRunner | None = None, jwks: JWKSCache | None = None,
    run_migrations: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    cfg = cfg or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.require_ffmpeg:
            check_ffmpeg()
        nonlocal engine, runner, jwks
        if engine is None:
            if run_migrations:
                upgrade_to_head(settings.database_url)
            engine = make_engine(settings.database_url)
        if runner is None:
            from vocal_coach.jobs.runner import make_process_runner  # Task 4
            runner = make_process_runner(settings, cfg)
        if jwks is None:
            jwks = JWKSCache(settings.jwks_url)
        app.state.settings, app.state.cfg, app.state.engine = settings, cfg, engine
        app.state.session_factory = make_session_factory(engine)
        app.state.runner, app.state.jwks = runner, jwks
        with app.state.session_factory() as session:
            failed = repo.fail_stale_jobs(session)
            if failed:
                log.warning("marked %d stale job(s) failed after restart", failed)
        runner.start()
        try:
            yield
        finally:
            runner.stop()

    app = FastAPI(title="Vocal Coach API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(AuthError)
    async def _auth_error(_request, exc: AuthError):
        return JSONResponse({"detail": f"invalid token: {exc}"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    for router in (me.router, config_public.router, llm.router, analyses.router, jobs.router, comparisons.router):
        app.include_router(router, prefix=API_PREFIX)
    return app
```

For this task create `api/analyses.py` and `api/comparisons.py` as routers with no routes yet (`router = APIRouter()`), so the import works; Tasks 5–6 fill them. `api/jobs.py` gets the `GET /jobs/{id}` route now:

```python
"""Job status and progress (SSE arrives in Task 6)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.storage import repo

router = APIRouter(tags=["jobs"])


class JobStatus(BaseModel):
    id: uuid.UUID
    status: str
    stage: str
    progress_pct: int
    error: str | None
    analysis_id: uuid.UUID | None


def _status(job) -> JobStatus:
    return JobStatus(id=job.id, status=job.status, stage=job.stage, progress_pct=job.progress_pct,
                     error=job.error, analysis_id=job.analysis_id)


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    job = repo.get_job(session, user.id, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _status(job)
```

`api/me.py`:

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from vocal_coach.auth.deps import CurrentUser, get_current_user

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str | None
    username: str | None
    drive_connected: bool
    llm_enabled: bool
    llm_provider: str | None


@router.get("/me", response_model=MeResponse)
def me(request: Request, user: CurrentUser = Depends(get_current_user)):
    llm = request.app.state.cfg.raw.get("llm", {})
    return MeResponse(id=user.id, email=user.email, username=user.username,
                      drive_connected=False,  # Plan 7
                      llm_enabled=bool(llm.get("enabled", False)), llm_provider=llm.get("provider"))
```

`api/config_public.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from vocal_coach.auth.deps import CurrentUser, get_current_user

router = APIRouter(tags=["config"])


@router.get("/config/public")
def config_public(request: Request, _user: CurrentUser = Depends(get_current_user)) -> dict:
    cfg = request.app.state.cfg
    return {"analysis": cfg.analysis.model_dump(), "articulation": cfg.articulation.model_dump(),
            "clarity": cfg.clarity.model_dump(), "comparison": cfg.comparison.model_dump()}
```

`api/llm.py`:

```python
"""LLM endpoints. Stubs until Plan 6 wires providers."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.storage import repo

router = APIRouter(tags=["llm"])


@router.get("/llm/models")
def list_models(_user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"enabled": False, "provider": None, "models": []}


@router.post("/analyses/{analysis_id}/coach", status_code=501)
def coach(analysis_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    if repo.get_analysis(session, user.id, analysis_id) is None:
        raise HTTPException(404, "analysis not found")
    raise HTTPException(501, "coaching is not available yet")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_app.py -v -W error`
Expected: 5 passed. If `TestClient` emits a `DeprecationWarning` from `httpx` about `app=` shortcut, upgrade the call to `TestClient(app)` as written (Starlette handles the transport); report any other warning verbatim.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/main.py backend/vocal_coach/api backend/vocal_coach/jobs backend/tests/api_fixtures.py backend/tests/test_app.py
git commit -m "feat(api): app factory with lifespan, auth-protected /me, /config/public, LLM stubs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Process-pool job runner and worker entry point

**Files:**
- Modify: `backend/vocal_coach/jobs/runner.py` (add `run_job`, `make_process_runner`)
- Create: `backend/tests/test_jobs.py`

**Interfaces:**
- Produces: `run_job(req: JobRequest, database_url: str, config_path: str | None, *, whisper_model=None) -> None` — runs in a worker: builds its own engine/session, `load_config(config_path)`, `progress` callback = `repo.update_job(status="running", stage, progress_pct)`, calls `run_pipeline`; on success `update_job(status="done", stage="done", progress_pct=100, analysis_id=...)`; on any exception `update_job(status="failed", error=<message truncated to ERROR_MAX_CHARS>)` and logs the traceback; never raises out of the worker. `make_process_runner(settings, cfg) -> JobRunner` with `ProcessPoolExecutor(max_workers=settings.job_workers, mp_context=multiprocessing.get_context("spawn"))` and `job_fn=run_job`. `ERROR_MAX_CHARS = 2000`.

- [ ] **Step 1: Failing tests**

`backend/tests/test_jobs.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests import synth
from tests.conftest import requires_ffmpeg
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.config import load_config
from vocal_coach.jobs.runner import ERROR_MAX_CHARS, JobRunner, SyncExecutor, make_process_runner, run_job
from vocal_coach.pipeline import JobRequest
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.storage.db import create_all, make_engine, make_session_factory


@pytest.fixture
def db(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(url)
    create_all(engine)
    return url, make_session_factory(engine)


def _fake():
    return FakeWhisper([seg(0.0, 1.0, " Hi.", [word(0.0, 0.5, " Hi.", 0.9)])])


@requires_ffmpeg
def test_run_job_marks_done_with_analysis(db, tmp_path: Path, monkeypatch):
    url, factory = db
    with factory() as s:
        user = repo.upsert_user(s, "sub", None, None)
        job = repo.create_job(s, user.id)
    src = synth.write_wav(tmp_path / "r.wav", synth.with_noise_floor(synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)))
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=src, file_name="r.wav",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    run_job(req, url, None, whisper_model=_fake())
    with factory() as s:
        j = repo.get_job(s, user.id, job.id)
        assert (j.status, j.stage, j.progress_pct) == ("done", "done", 100)
        assert j.analysis_id is not None and repo.get_analysis(s, user.id, j.analysis_id) is not None


def test_run_job_marks_failed_on_bad_input(db, tmp_path: Path, monkeypatch):
    url, factory = db
    with factory() as s:
        user = repo.upsert_user(s, "sub", None, None)
        job = repo.create_job(s, user.id)
    bad = tmp_path / "x.mp3"
    bad.write_bytes(b"not audio")
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=bad, file_name="x.mp3",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    run_job(req, url, None, whisper_model=_fake())  # must not raise
    with factory() as s:
        j = repo.get_job(s, user.id, job.id)
        assert j.status == "failed" and j.error and len(j.error) <= ERROR_MAX_CHARS
        assert "ffmpeg" in j.error.lower() or "decode" in j.error.lower()


def test_run_job_failure_before_pipeline_is_recorded(db, tmp_path: Path):
    url, factory = db
    with factory() as s:
        user = repo.upsert_user(s, "sub", None, None)
        job = repo.create_job(s, user.id)
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=tmp_path / "missing.wav", file_name="missing.wav",
                     recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    run_job(req, url, None)
    with factory() as s:
        assert repo.get_job(s, user.id, job.id).status == "failed"


def test_sync_runner_submit_runs_job_fn(tmp_path):
    calls = []
    runner = JobRunner(Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:"), load_config(),
                       executor=SyncExecutor(), job_fn=lambda req, url, path: calls.append((req.file_name, url)))
    runner.start()
    req = JobRequest(job_id=__import__("uuid").uuid4(), user_id=__import__("uuid").uuid4(), source_path=tmp_path,
                     file_name="f.wav", recorded_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    fut = runner.submit(req)
    assert fut.done() and calls == [("f.wav", "sqlite+pysqlite:///:memory:")]
    runner.stop()


def test_make_process_runner_uses_spawn_pool():
    runner = make_process_runner(Settings(_env_file=None, job_workers=1), load_config())
    runner.start()
    try:
        ex = runner._executor
        assert type(ex).__name__ == "ProcessPoolExecutor" and ex._max_workers == 1
        assert ex._mp_context.get_start_method() == "spawn"
    finally:
        runner.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jobs.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_job'`

- [ ] **Step 3: Implement** (append to `runner.py`)

```python
import multiprocessing
import traceback
from concurrent.futures import ProcessPoolExecutor

from vocal_coach.config import load_config
from vocal_coach.pipeline import run_pipeline
from vocal_coach.settings import get_settings
from vocal_coach.storage import repo as _repo
from vocal_coach.storage.db import make_engine, make_session_factory

ERROR_MAX_CHARS = 2000  # jobs.error is TEXT, but the UI shows one line; keep stack noise out of the row
MP_START_METHOD = "spawn"  # fork is unsafe with parselmouth/ctranslate2 threads already alive in the parent


def run_job(req: JobRequest, database_url: str, config_path: str | None, *, whisper_model=None) -> None:
    """Worker entry point. Owns its own engine/session; never raises."""
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    try:
        cfg = load_config(Path(config_path) if config_path else None)
        settings = get_settings().model_copy(update={"database_url": database_url})
        with factory() as session:
            def progress(stage: str, pct: int) -> None:
                _repo.update_job(session, req.job_id, status="running", stage=stage, progress_pct=pct)

            try:
                analysis_id = run_pipeline(req, cfg, settings, session, progress, whisper_model=whisper_model)
                _repo.update_job(session, req.job_id, status="done", stage="done", progress_pct=100, analysis_id=analysis_id)
            except Exception as e:
                log.error("job %s failed:\n%s", req.job_id, traceback.format_exc())
                session.rollback()
                _repo.update_job(session, req.job_id, status="failed", error=str(e)[:ERROR_MAX_CHARS])
    except Exception:  # could not even reach the database: log, nothing else to do in a worker
        log.error("job %s could not be recorded:\n%s", req.job_id, traceback.format_exc())
    finally:
        engine.dispose()


def make_process_runner(settings: Settings, cfg: AppConfig, config_path: str | None = None) -> JobRunner:
    pool = ProcessPoolExecutor(max_workers=settings.job_workers, mp_context=multiprocessing.get_context(MP_START_METHOD))
    return JobRunner(settings, cfg, executor=pool, job_fn=run_job, config_path=config_path)
```

(`from pathlib import Path` at the top.) The `DATA_DIR` env is read by `get_settings()` inside the worker; the parent passes nothing else. Note in the docstring that the worker inherits environment, not the parent's `Settings` object.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_jobs.py -v -W error`
Expected: 5 passed. `test_make_process_runner_uses_spawn_pool` only constructs the pool (no task submitted) so no worker process is spawned.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/jobs/runner.py backend/tests/test_jobs.py
git commit -m "feat(jobs): worker entry point recording progress and failures; spawn process pool

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Analyses API (upload, list, detail, raw, delete)

**Files:**
- Modify: `backend/vocal_coach/api/analyses.py`
- Modify: `backend/vocal_coach/storage/repo.py` (add `count_analyses_with_sha(session, user_id, sha) -> int`)
- Create: `backend/tests/test_api_analyses.py`

**Interfaces:**
- `POST /api/analyses` multipart: `file: UploadFile` (required), `speaker_context: str | None = Form(None)`, `llm_enabled: bool = Form(False)`, `llm_model: str | None = Form(None)` → 202 `{"job_ids": [str]}`. JSON body with `source: "drive"` → 501 `{"detail": "drive is not available yet"}`. Extension not in `ALLOWED_EXTENSIONS = {"m4a","mp3","wav","mov","mp4"}` → 415. Size > `settings.max_upload_bytes` (checked while streaming to disk in `UPLOAD_CHUNK_BYTES = 1 MiB` chunks, sha256 computed on the fly) → 413 and the partial file removed. Stored at `data_dir/uploads/<user_id>/<sha>.<ext>` (reused if present). `recorded_at = now (UTC)`. Creates a job and submits a `JobRequest`.
- `GET /api/analyses?limit=&offset=` → `list[AnalysisSummary]` (`limit` 1–200, default 50).
- `GET /api/analyses/{id}` → `AnalysisDetail(id, file_name, drive_file_id, recorded_at, analysed_at, analyser_version, config_hash, metrics: dict, transcript: dict | None, speaker_context, coaching: dict | None, coaching_warnings: list | None)`; 404 if foreign/missing.
- `GET /api/analyses/{id}/raw/{kind}` with `kind ∈ metrics|transcript|coaching` → `application/json` body re-serialised canonically (`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`), `Content-Disposition: attachment; filename="<stem>.<kind>.json"`; 404 if the analysis is missing or that kind is null.
- `DELETE /api/analyses/{id}` → 204; removes the upload file if `count_analyses_with_sha(...) == 0` after deletion; 404 if foreign/missing.

- [ ] **Step 1: Failing tests**

`backend/tests/test_api_analyses.py`:

```python
import io
import json
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from tests import synth
from tests.api_fixtures import make_test_app
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


def test_list_pagination(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        for i in range(3):
            _upload(client, ctx["auth"](), name=f"c{i}.wav", data=_wav_bytes(1.0 + 0.1 * i))
        assert len(client.get("/api/analyses?limit=2", headers=ctx["auth"]()).json()) == 2
        assert len(client.get("/api/analyses?limit=2&offset=2", headers=ctx["auth"]()).json()) == 1
        assert client.get("/api/analyses?limit=0", headers=ctx["auth"]()).status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_analyses.py -v`
Expected: FAIL with 404/405 responses (routes missing).

- [ ] **Step 3: Implement**

`repo.py` addition:

```python
def count_analyses_with_sha(session: Session, user_id: uuid.UUID, content_sha256: str) -> int:
    return int(session.scalar(select(func.count()).select_from(Analysis).where(
        Analysis.user_id == user_id, Analysis.content_sha256 == content_sha256)) or 0)
```

`backend/vocal_coach/api/analyses.py`:

```python
"""Upload, list, detail, raw download and delete for a user's analyses."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.pipeline import JobRequest
from vocal_coach.storage import repo
from vocal_coach.storage.repo import AnalysisSummary

router = APIRouter(tags=["analyses"])

ALLOWED_EXTENSIONS = frozenset({"m4a", "mp3", "wav", "mov", "mp4"})  # spec §5
UPLOAD_CHUNK_BYTES = 1024 * 1024
UPLOADS_SUBDIR = "uploads"
RAW_KINDS = ("metrics", "transcript", "coaching")
LIST_LIMIT_MIN, LIST_LIMIT_MAX, LIST_LIMIT_DEFAULT = 1, 200, repo.SUMMARY_PAGE_SIZE


class JobIds(BaseModel):
    job_ids: list[uuid.UUID]


class AnalysisDetail(BaseModel):
    id: uuid.UUID
    file_name: str
    drive_file_id: str | None
    recorded_at: datetime
    analysed_at: datetime
    analyser_version: str
    config_hash: str
    metrics: dict
    transcript: dict | None
    speaker_context: str | None
    coaching: dict | None
    coaching_warnings: list | None


def _detail(row) -> AnalysisDetail:
    return AnalysisDetail(id=row.id, file_name=row.file_name, drive_file_id=row.drive_file_id,
                          recorded_at=row.recorded_at, analysed_at=row.analysed_at, analyser_version=row.analyser_version,
                          config_hash=row.config_hash, metrics=row.metrics_json, transcript=row.transcript_json,
                          speaker_context=row.speaker_context, coaching=row.coaching_json,
                          coaching_warnings=row.coaching_warnings)


async def _store_upload(file: UploadFile, dest_dir: Path, max_bytes: int) -> tuple[Path, str, int]:
    """Stream to a temp file, hashing as we go. Returns (final_path, sha256, size). Raises 413 on overflow."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f".upload-{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"file exceeds {max_bytes} bytes")
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    sha = digest.hexdigest()
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    final = dest_dir / f"{sha}.{ext}"
    if final.exists():
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(final)
    return final, sha, size


@router.post("/analyses", status_code=status.HTTP_202_ACCEPTED, response_model=JobIds)
async def create_analysis(
    request: Request,
    file: UploadFile | None = File(None),
    speaker_context: str | None = Form(None),
    llm_enabled: bool = Form(False),
    llm_model: str | None = Form(None),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if file is None:
        # JSON body (Drive source) — Plan 7
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "drive is not available yet")
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported file type .{ext}; allowed: {sorted(ALLOWED_EXTENSIONS)}")
    settings = request.app.state.settings
    dest_dir = settings.data_dir / UPLOADS_SUBDIR / str(user.id)
    path, sha, _size = await _store_upload(file, dest_dir, settings.max_upload_bytes)
    job = repo.create_job(session, user.id)
    req = JobRequest(job_id=job.id, user_id=user.id, source_path=path, file_name=file.filename or path.name,
                     recorded_at=datetime.now(timezone.utc), speaker_context=speaker_context,
                     llm_enabled=llm_enabled, llm_model=llm_model)
    request.app.state.runner.submit(req)
    return JobIds(job_ids=[job.id])


@router.get("/analyses", response_model=list[AnalysisSummary])
def list_analyses(
    limit: int = Query(LIST_LIMIT_DEFAULT, ge=LIST_LIMIT_MIN, le=LIST_LIMIT_MAX),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
):
    return repo.list_analysis_summaries(session, user.id, limit=limit, offset=offset)


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetail)
def get_analysis(analysis_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    row = repo.get_analysis(session, user.id, analysis_id)
    if row is None:
        raise HTTPException(404, "analysis not found")
    return _detail(row)


@router.get("/analyses/{analysis_id}/raw/{kind}")
def get_raw(analysis_id: uuid.UUID, kind: str, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    if kind not in RAW_KINDS:
        raise HTTPException(404, f"unknown kind {kind!r}")
    row = repo.get_analysis(session, user.id, analysis_id)
    if row is None:
        raise HTTPException(404, "analysis not found")
    payload = {"metrics": row.metrics_json, "transcript": row.transcript_json, "coaching": row.coaching_json}[kind]
    if payload is None:
        raise HTTPException(404, f"no {kind} for this analysis")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)  # JSONB reorders keys
    stem = Path(row.file_name).stem
    return RawResponse(body, media_type="application/json",
                       headers={"Content-Disposition": f'attachment; filename="{stem}.{kind}.json"'})


@router.delete("/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(analysis_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user),
                    session: Session = Depends(get_session)):
    row = repo.get_analysis(session, user.id, analysis_id)
    if row is None:
        raise HTTPException(404, "analysis not found")
    sha = row.content_sha256
    repo.delete_analysis(session, user.id, analysis_id)
    if repo.count_analyses_with_sha(session, user.id, sha) == 0:
        for f in (request.app.state.settings.data_dir / UPLOADS_SUBDIR / str(user.id)).glob(f"{sha}.*"):
            f.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api_analyses.py -v -W error`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/api/analyses.py backend/vocal_coach/storage/repo.py backend/tests/test_api_analyses.py
git commit -m "feat(api): analyses upload, list, detail, raw download and delete

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Job SSE stream and comparisons API

**Files:**
- Modify: `backend/vocal_coach/api/jobs.py` (add SSE)
- Create: `backend/vocal_coach/jobs/events.py`
- Modify: `backend/vocal_coach/api/comparisons.py`
- Create: `backend/tests/test_api_jobs_sse.py`
- Create: `backend/tests/test_api_comparisons.py`

**Interfaces:**
- Produces (`jobs/events.py`): `POLL_INTERVAL_S = 0.5`; `async def job_events(session_factory, user_id, job_id, *, poll_interval_s: float = POLL_INTERVAL_S, max_duration_s: float = MAX_STREAM_S) -> AsyncIterator[dict]` yielding sse-starlette event dicts `{"event": "stage"|"progress"|"done"|"error", "data": json}`; opens a fresh session per poll; emits `stage` when stage changes, `progress` when pct changes, then `done {"analysis_id"}` or `error {"message"}` and returns; if the job disappears → `error {"message": "job not found"}`; `MAX_STREAM_S = 3600`.
- Produces (`api/jobs.py`): `GET /api/jobs/{id}/events` → `EventSourceResponse(job_events(...))`; 404 before streaming if the job is not the user's.
- Produces (`api/comparisons.py`): `GET /api/comparisons?ids=a,b,c` → `ComparisonResult`; 400 `{"detail": "need at least two distinct ids"}` or on a non-UUID; 404 if any id is not the user's.

- [ ] **Step 1: Failing tests**

`backend/tests/test_api_jobs_sse.py`:

```python
import json
import uuid

from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.test_api_analyses import _upload, fake_job_fn, failing_job_fn
from vocal_coach.storage import repo


def _events(resp):
    out, event = [], {}
    for line in resp.iter_lines():
        if line.startswith("event:"):
            event["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            event["data"] = json.loads(line.split(":", 1)[1].strip())
        elif line == "" and event:
            out.append(event); event = {}
    return out


def test_sse_on_finished_job_emits_terminal_event_and_closes(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        with client.stream("GET", f"/api/jobs/{job_id}/events", headers=ctx["auth"]()) as resp:
            assert resp.status_code == 200
            events = _events(resp)
    kinds = [e["event"] for e in events]
    assert kinds[-1] == "done" and events[-1]["data"]["analysis_id"]
    assert "stage" in kinds and "progress" in kinds


def test_sse_failed_job_emits_error(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=failing_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        with client.stream("GET", f"/api/jobs/{job_id}/events", headers=ctx["auth"]()) as resp:
            events = _events(resp)
    assert events[-1]["event"] == "error" and events[-1]["data"]["message"] == "boom"


def test_sse_foreign_job_is_404(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]("alice")).json()["job_ids"][0]
        assert client.get(f"/api/jobs/{job_id}/events", headers=ctx["auth"]("bob")).status_code == 404
        assert client.get(f"/api/jobs/{uuid.uuid4()}/events", headers=ctx["auth"]("alice")).status_code == 404


def test_job_events_generator_streams_progress(tmp_path):
    """Drive the generator directly: a running job that is advanced between polls."""
    import asyncio
    from vocal_coach.jobs.events import job_events

    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    factory = ctx["session_factory"]
    with factory() as s:
        user = repo.upsert_user(s, "u", None, None)
        job = repo.create_job(s, user.id)

    async def run():
        gen = job_events(factory, user.id, job.id, poll_interval_s=0.01)
        seen = []
        seen.append(await gen.__anext__())  # initial stage
        with factory() as s:
            repo.update_job(s, job.id, status="running", stage="analyse", progress_pct=55)
        seen.append(await gen.__anext__())
        seen.append(await gen.__anext__())
        with factory() as s:
            repo.update_job(s, job.id, status="done", stage="done", progress_pct=100)
        async for e in gen:
            seen.append(e)
        return seen

    seen = asyncio.run(run())
    kinds = [e["event"] for e in seen]
    assert kinds[0] == "stage" and "progress" in kinds and kinds[-1] == "done"
```

`backend/tests/test_api_comparisons.py`:

```python
import uuid

from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.test_api_analyses import _upload, _wav_bytes, fake_job_fn


def _ids(client, headers, n):
    out = []
    for i in range(n):
        job_id = _upload(client, headers, name=f"r{i}.wav", data=_wav_bytes(1.0 + 0.2 * i)).json()["job_ids"][0]
        out.append(client.get(f"/api/jobs/{job_id}", headers=headers).json()["analysis_id"])
    return out


def test_comparison_two_analyses(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        a, b = _ids(client, ctx["auth"](), 2)
        r = client.get(f"/api/comparisons?ids={a},{b}", headers=ctx["auth"]())
        assert r.status_code == 200
        body = r.json()
        assert set(body["analysis_ids"]) == {a, b} and body["config_mismatch"] is False
        paths = {row["path"]: row for row in body["rows"]}
        assert paths["pitch.f0_range_st"]["verdict"] == "unchanged"
        assert paths["transcript.derived.clarity.rushed_word_fraction"]["verdict"] == "unavailable"
        assert set(body["trend"]) == set(paths)


def test_comparison_validation_and_scoping(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        a, b = _ids(client, ctx["auth"]("alice"), 2)
        assert client.get(f"/api/comparisons?ids={a}", headers=ctx["auth"]("alice")).status_code == 400
        assert client.get(f"/api/comparisons?ids={a},{a}", headers=ctx["auth"]("alice")).status_code == 400
        assert client.get("/api/comparisons?ids=nope,also", headers=ctx["auth"]("alice")).status_code == 400
        assert client.get(f"/api/comparisons?ids={a},{uuid.uuid4()}", headers=ctx["auth"]("alice")).status_code == 404
        assert client.get(f"/api/comparisons?ids={a},{b}", headers=ctx["auth"]("bob")).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_jobs_sse.py tests/test_api_comparisons.py -v`
Expected: FAIL (`ModuleNotFoundError: vocal_coach.jobs.events`, 404s).

- [ ] **Step 3: Implement**

`backend/vocal_coach/jobs/events.py`:

```python
"""Server-sent events for one job: poll the row, emit on change, stop on a terminal status."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import AsyncIterator

from vocal_coach.storage import repo

POLL_INTERVAL_S = 0.5  # spec §10
MAX_STREAM_S = 3600.0  # a 90-minute recording takes ~10 min; cap runaway streams at an hour
TERMINAL = {"done", "failed"}


def _event(name: str, data: dict) -> dict:
    return {"event": name, "data": json.dumps(data)}


async def job_events(session_factory, user_id: uuid.UUID, job_id: uuid.UUID, *,
                     poll_interval_s: float = POLL_INTERVAL_S, max_duration_s: float = MAX_STREAM_S) -> AsyncIterator[dict]:
    last_stage: str | None = None
    last_pct: int | None = None
    started = time.monotonic()
    while True:
        with session_factory() as session:  # one short session per poll (Plan 3 note)
            job = repo.get_job(session, user_id, job_id)
            snap = None if job is None else (job.status, job.stage, job.progress_pct, job.error, job.analysis_id)
        if snap is None:
            yield _event("error", {"message": "job not found"})
            return
        status, stage, pct, error, analysis_id = snap
        if stage != last_stage:
            yield _event("stage", {"stage": stage, "progress_pct": pct})
            last_stage = stage
        if pct != last_pct:
            yield _event("progress", {"progress_pct": pct, "stage": stage})
            last_pct = pct
        if status in TERMINAL:
            if status == "done":
                yield _event("done", {"analysis_id": str(analysis_id) if analysis_id else None})
            else:
                yield _event("error", {"message": error or "job failed"})
            return
        if time.monotonic() - started > max_duration_s:
            yield _event("error", {"message": "stream timeout"})
            return
        await asyncio.sleep(poll_interval_s)
```

`api/jobs.py` addition:

```python
from sse_starlette.sse import EventSourceResponse
from vocal_coach.jobs.events import job_events


@router.get("/jobs/{job_id}/events")
def job_event_stream(job_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user),
                     session: Session = Depends(get_session)):
    if repo.get_job(session, user.id, job_id) is None:
        raise HTTPException(404, "job not found")
    return EventSourceResponse(job_events(request.app.state.session_factory, user.id, job_id))
```

`api/comparisons.py`:

```python
"""Compare two or more of the user's analyses."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from vocal_coach.auth.deps import CurrentUser, get_current_user, get_session
from vocal_coach.storage import repo
from vocal_coach.storage.comparison import ComparisonResult, compare, from_row

router = APIRouter(tags=["comparisons"])
MIN_IDS = 2


def _parse_ids(raw: str) -> list[uuid.UUID]:
    try:
        ids = [uuid.UUID(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(400, "ids must be comma-separated UUIDs")
    unique = list(dict.fromkeys(ids))
    if len(unique) < MIN_IDS:
        raise HTTPException(400, f"need at least {MIN_IDS} distinct ids")
    return unique


@router.get("/comparisons", response_model=ComparisonResult)
def get_comparison(request: Request, ids: str = Query(..., description="comma-separated analysis ids"),
                   user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session)):
    wanted = _parse_ids(ids)
    rows = repo.get_analyses(session, user.id, wanted)
    if len(rows) != len(wanted):
        raise HTTPException(404, "one or more analyses not found")
    return compare([from_row(r) for r in rows], request.app.state.cfg.comparison)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api_jobs_sse.py tests/test_api_comparisons.py -v -W error`
Expected: 6 passed. If `sse-starlette` emits a `DeprecationWarning` under `-W error` on import, report the exact message; a targeted `filterwarnings` on the SSE tests is acceptable only with that exact message and must be in the report.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/api/jobs.py backend/vocal_coach/jobs/events.py backend/vocal_coach/api/comparisons.py backend/tests/test_api_jobs_sse.py backend/tests/test_api_comparisons.py
git commit -m "feat(api): job progress over SSE and comparisons endpoint

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Docker image, compose stack, Keycloak realm, env example, smoke script, README

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/entrypoint.sh`
- Create: `docker-compose.yml` (repo root)
- Create: `.env.example` (repo root)
- Create: `keycloak/realm-export.json`
- Create: `deploy/postgres-init/01-databases.sql`
- Create: `scripts/smoke.sh`
- Modify: `.gitignore` (add `data/` already present; add `backend/data/`)
- Modify: `backend/README.md` (append "Running the API")

**Interfaces:** none new. Verified by `scripts/smoke.sh` and by the controller's compose run.

- [ ] **Step 1: Files**

`backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml requirements.lock alembic.ini ./
COPY alembic ./alembic
COPY vocal_coach ./vocal_coach
COPY config.yaml ./config.yaml
COPY entrypoint.sh ./entrypoint.sh
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir -e . && chmod +x entrypoint.sh
ENV DATA_DIR=/data HF_HOME=/models
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
```

`backend/entrypoint.sh`:

```bash
#!/usr/bin/env sh
set -eu
# Migrations run once here, in a single process, before uvicorn starts (spec §14; Plan 3 note).
python -c "import os; from vocal_coach.storage.migrate import upgrade_to_head; upgrade_to_head(os.environ['DATABASE_URL'])"
exec uvicorn "vocal_coach.main:create_app" --factory --host 0.0.0.0 --port 8000 --workers 1
```

`deploy/postgres-init/01-databases.sql`:

```sql
CREATE DATABASE keycloak;
-- vocal_coach is created by POSTGRES_DB
```

`docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-vocal}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-vocal}
      POSTGRES_DB: vocal_coach
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./deploy/postgres-init:/docker-entrypoint-initdb.d:ro
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-vocal} -d vocal_coach"]
      interval: 5s
      timeout: 3s
      retries: 20

  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    command: ["start-dev", "--import-realm", "--http-port=8080"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: ${KEYCLOAK_ADMIN:-admin}
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${KEYCLOAK_ADMIN_PASSWORD:-admin}
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: ${POSTGRES_USER:-vocal}
      KC_DB_PASSWORD: ${POSTGRES_PASSWORD:-vocal}
      KC_HOSTNAME: localhost
      KC_HTTP_ENABLED: "true"
    volumes:
      - ./keycloak/realm-export.json:/opt/keycloak/data/import/realm-export.json:ro
    ports: ["8080:8080"]
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/8080 && echo -e 'GET /realms/vocal-coach HTTP/1.0\r\n\r\n' >&3 && grep -q '\"realm\"' <&3"]
      interval: 10s
      timeout: 5s
      retries: 30

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-vocal}:${POSTGRES_PASSWORD:-vocal}@postgres:5432/vocal_coach
      KEYCLOAK_ISSUER: ${KEYCLOAK_ISSUER:-http://localhost:8080/realms/vocal-coach}
      KEYCLOAK_AUDIENCE: ${KEYCLOAK_AUDIENCE:-vocal-coach-web}
      KEYCLOAK_JWKS_URL_OVERRIDE: http://keycloak:8080/realms/vocal-coach/protocol/openid-connect/certs
      FRONTEND_ORIGIN: ${FRONTEND_ORIGIN:-http://localhost:5173}
      DATA_DIR: /data
      JOB_WORKERS: ${JOB_WORKERS:-1}
      MAX_UPLOAD_MB: ${MAX_UPLOAD_MB:-500}
    volumes:
      - appdata:/data
      - models:/models
    ports: ["8000:8000"]
    depends_on:
      postgres:
        condition: service_healthy
      keycloak:
        condition: service_healthy

volumes:
  pgdata:
  appdata:
  models:
```

The issuer in tokens is `http://localhost:8080/realms/vocal-coach` (what the browser sees), but the backend container must fetch JWKS from `http://keycloak:8080`; `KEYCLOAK_JWKS_URL_OVERRIDE` (Task 1's setting) handles that.

`keycloak/realm-export.json` (minimal; Keycloak fills defaults):

```json
{
  "realm": "vocal-coach",
  "enabled": true,
  "registrationAllowed": true,
  "loginWithEmailAllowed": true,
  "sslRequired": "none",
  "roles": {"realm": [{"name": "user", "description": "Vocal Coach user"}]},
  "defaultRoles": ["user", "offline_access", "uma_authorization"],
  "clients": [
    {
      "clientId": "vocal-coach-web",
      "name": "Vocal Coach web",
      "publicClient": true,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": true,
      "implicitFlowEnabled": false,
      "serviceAccountsEnabled": false,
      "redirectUris": ["http://localhost:5173/*", "http://localhost:3000/*"],
      "webOrigins": ["http://localhost:5173", "http://localhost:3000"],
      "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "http://localhost:5173/*"},
      "protocolMappers": [
        {
          "name": "vocal-coach-web audience",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-audience-mapper",
          "consentRequired": false,
          "config": {"included.client.audience": "vocal-coach-web", "id.token.claim": "false", "access.token.claim": "true"}
        }
      ]
    }
  ],
  "users": [
    {
      "username": "demo",
      "enabled": true,
      "email": "demo@example.test",
      "emailVerified": true,
      "firstName": "Demo",
      "lastName": "User",
      "credentials": [{"type": "password", "value": "demo", "temporary": false}],
      "realmRoles": ["user"]
    }
  ]
}
```

`directAccessGrantsEnabled: true` exists so `scripts/smoke.sh` can obtain a token with the password grant; the README says to turn it off outside local development. `defaultRoles` is the legacy key; if Keycloak 26 rejects it, use `"defaultRole": {"name": "default-roles-vocal-coach", "composite": true, "composites": {"realm": ["user", "offline_access", "uma_authorization"]}}` instead and say so in the report.

`.env.example`:

```dotenv
# Postgres (compose)
POSTGRES_USER=vocal
POSTGRES_PASSWORD=vocal
# Keycloak (compose)
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=admin
KEYCLOAK_ISSUER=http://localhost:8080/realms/vocal-coach
KEYCLOAK_AUDIENCE=vocal-coach-web
# Backend
DATABASE_URL=postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach
FRONTEND_ORIGIN=http://localhost:5173
DATA_DIR=data
JOB_WORKERS=1
MAX_UPLOAD_MB=500
# Later plans
SECRET_KEY=
DRIVE_TOKEN_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/drive/callback
OPENAI_COMPAT_API_KEY=
ANTHROPIC_API_KEY=
```

`scripts/smoke.sh`:

```bash
#!/usr/bin/env bash
# Bring the stack up, obtain a token for the demo user, hit /api/me, upload a WAV, wait for the job.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d --build
echo "waiting for backend…"
for _ in $(seq 1 60); do curl -fsS http://localhost:8000/docs >/dev/null 2>&1 && break; sleep 2; done
TOKEN=$(curl -fsS -X POST http://localhost:8080/realms/vocal-coach/protocol/openid-connect/token \
  -d client_id=vocal-coach-web -d grant_type=password -d username=demo -d password=demo | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -fsS http://localhost:8000/api/me -H "Authorization: Bearer $TOKEN"; echo
WAV=${1:-}
if [ -n "$WAV" ]; then
  JOB=$(curl -fsS -X POST http://localhost:8000/api/analyses -H "Authorization: Bearer $TOKEN" -F "file=@$WAV" | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_ids"][0])')
  echo "job $JOB"
  curl -NsS "http://localhost:8000/api/jobs/$JOB/events" -H "Authorization: Bearer $TOKEN"
fi
```

README append:

````markdown
## Running the API (Plan 4)

```bash
cp .env.example .env               # edit if needed
docker compose up -d --build       # postgres + keycloak (realm imported, user demo/demo) + backend
./scripts/smoke.sh path/to/recording.wav   # token → /api/me → upload → SSE progress
```

Dev loop: `docker compose up -d postgres keycloak`, then from `backend/`:
`DATABASE_URL=postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach uvicorn "vocal_coach.main:create_app" --factory --reload`.
Migrations run once in the container entrypoint; with `--reload` locally run `alembic upgrade head` yourself.

Auth: Bearer tokens from Keycloak realm `vocal-coach`, client `vocal-coach-web` (public, PKCE). The realm export adds an
audience mapper so access tokens carry `aud: vocal-coach-web`; without it Keycloak only emits `aud: account` and the API
answers 401. `directAccessGrantsEnabled` is on only so `scripts/smoke.sh` can use the password grant — turn it off
outside local development.

Jobs run in a spawn-based process pool (`JOB_WORKERS`, default 1): praat-parselmouth and CTranslate2 are not safe to share
across threads, and each worker loads the whisper model once. Progress is written to the `jobs` row and streamed by
`GET /api/jobs/{id}/events`. On restart, unfinished jobs are marked `failed / server restarted`. Run exactly one backend
process per database (the restart sweep is not multi-process safe).

Endpoints: see `/docs`. Drive (`/api/drive/*`, `source: "drive"`) and coaching (`/api/analyses/{id}/coach`,
`/api/llm/models`) are stubs until Plans 6–7.
````

- [ ] **Step 2: Build and run locally**

```bash
docker compose build backend && docker compose up -d && sleep 30 && ./scripts/smoke.sh
```

Expected: `/api/me` prints the demo user's JSON. Then run the smoke with a WAV: `./scripts/smoke.sh backend/tests/...` — there is no checked-in WAV; generate one: `backend/.venv/bin/python -c "from tests import synth; from pathlib import Path; synth.write_wav(Path('/tmp/demo.wav'), synth.with_noise_floor(synth.am(synth.vowel(500,1500,120,4.0),4.0)))"` from `backend/`, then `./scripts/smoke.sh /tmp/demo.wav`. Expected: SSE events ending in `done`. The first job downloads the whisper model into the `models` volume (~460 MB) so allow a few minutes. Record the output in the report. If Keycloak rejects the realm JSON, fix the JSON (see the `defaultRoles` note) and re-run `docker compose up -d --force-recreate keycloak`.

- [ ] **Step 3: Full test suite and commit**

Run: `pytest -v -W error` → all green.

```bash
git add backend/Dockerfile backend/entrypoint.sh docker-compose.yml .env.example keycloak/realm-export.json deploy/postgres-init/01-databases.sql scripts/smoke.sh .gitignore backend/README.md
git commit -m "feat(deploy): Dockerfile, compose stack with Keycloak realm import, smoke script, README

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage:** §4 auth → Task 2 (+ API wiring Task 3); §10 jobs → Tasks 4, 6; §12 endpoints: `/me`, `/config/public`, `/llm/models` (stub), `/analyses` POST/GET/GET id/DELETE, `/analyses/{id}/coach` (501), `/jobs/{id}`, `/jobs/{id}/events`, `/comparisons` → Tasks 3, 5, 6; `/drive/*` → Plan 7 (501 on `source: drive`); §14 → Task 7; §15 errors: 401, 413, 415, job failure, ffmpeg check, transcript degrade → Tasks 1–5; §16 `test_auth`, `test_jobs`, `test_api_analyses` present.
- **Deviations, deliberate:** spec §10 says `ThreadPoolExecutor`; this plan uses a spawn `ProcessPoolExecutor` because Plans 1–2 established that parselmouth and CTranslate2 must not be shared across threads, and each worker caches one whisper model. Worker writes progress to the DB directly (no in-process callback), which is what the SSE poller needs anyway. Added `GET /analyses/{id}/raw/{kind}` for canonical downloads (JSONB reorders keys). `keycloak_jwks_url_override` added so the container fetches JWKS via the compose network while the issuer stays the browser-visible URL.
- **Type consistency:** `JobRequest` (Task 1) → Tasks 3–6; `JobRunner/SyncExecutor` (Task 3) → Tasks 4–6 tests via `api_fixtures`; `run_job` (Task 4) → `make_process_runner` → `main.py` lazy import; `JobStatus` (Task 3) reused by Task 6; `AnalysisSummary` (Plan 3) → Task 5 response model; `ComparisonResult` (Plan 3) → Task 6 response model; `fake_job_fn/failing_job_fn/_upload/_wav_bytes` (Task 5 tests) → Task 6 tests.
- **Review Focus pins:** 1 → `test_account_only_audience_is_rejected` (T2) + `test_account_only_audience_rejected_at_api` (T3) + realm mapper (T7); 2 → `test_run_job_marks_failed_on_bad_input` (T4); 3 → `test_pipeline_dedupes_same_file_same_config` (T1) + Plan 3's race-safe `create_analysis`; 4 → `test_sse_on_finished_job_emits_terminal_event_and_closes` (T6); 5 → `test_lifespan_fails_stale_jobs` (T3).
- **Known limits recorded for later plans:** single backend process; `fail_stale_jobs` sweep is not multi-process safe; SSE streams hold no DB connection between polls but do hold an HTTP worker; whisper model download happens on the first job inside the container (~460 MB).
