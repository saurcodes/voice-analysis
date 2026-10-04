# Vocal Coach — backend

## Analysis core (Plan 1)

Deterministic voice metrics from any audio/video file. Same file + same `config.yaml` → byte-identical `metrics.json`.

### Prerequisites

- Python 3.11+
- ffmpeg and ffprobe on PATH (`brew install ffmpeg` / `apt install ffmpeg`)

### Setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Run

```bash
python -m vocal_coach.analysis.analyser path/to/recording.m4a --out data/metrics.json
```

Options: `--work-dir` (where the extracted WAV goes, default `data/work`), `--config` (alternative config.yaml).

### Test

```bash
pytest
```

Tests use synthetic audio only. ffmpeg-dependent tests are skipped if ffmpeg is missing.

### Determinism rules

- All thresholds live in `config.yaml` under `analysis` and `articulation`; `config_hash` covers both.
- Transcript-derived numbers are deliberately not part of `metrics.json` (see spec §2).
- Floats are rounded at serialisation (4 decimals; ratios 6) and keys sorted.

### Pinned dependencies

`requirements.lock` is the exact environment the determinism guarantee was verified in. Not every change to it requires a version bump — see "Pinned dependencies — what bumps `ANALYSER_VERSION`" under Transcription (Plan 2) below for the narrower rule.

## Transcription (Plan 2)

`transcript.json` = faster-whisper (CPU, `int8`, model size from `config.yaml → transcription.model_size`, beam 5, temperature 0, word timestamps) + filler counts + clarity proxies (low-confidence, half-eaten and rushed words). It is kept separate from `metrics.json` because whisper output is only deterministic for a fixed build and hardware.

With `transcription.language` set, whisper is forced to that language and `transcript.language` echoes the setting; set it to `null` to auto-detect. Whisper can invent words in silent stretches; any segment whose `no_speech_prob` exceeds `transcription.no_speech_exclude_prob` (default 0.6) is kept in `segments`/`words` but left out of every `derived` number.

```bash
python -m vocal_coach.transcription.run data/work/recording.wav --out data/transcript.json
```

The first run downloads the model (~460 MB for `small`) into the Hugging Face cache. Tests use a fake model; run the real one with `VOCAL_COACH_REAL_WHISPER=1 pytest tests/test_transcription_run.py`.

### Pinned dependencies — what bumps `ANALYSER_VERSION`

Only changes to packages that affect `metrics.json` numbers (praat-parselmouth, numpy, scipy, and the ffmpeg binary) require an `ANALYSER_VERSION` bump. Transcription packages (faster-whisper, ctranslate2, tokenizers) do not touch `metrics.json`; `transcript.json → model` records the model size only; package versions live in `requirements.lock`.

## Storage (Plan 3)

Postgres via SQLAlchemy 2 + Alembic. Tables: `users`, `drive_connections`, `analyses` (unique on user + file hash + config hash + analyser version, indexed on user + `recorded_at`), `jobs`. Every repository read is scoped by `user_id`; other users' rows read as missing. A Python `None` in a JSON column is stored as SQL `NULL`, and NaN/Infinity are rejected on every backend.

```bash
export DATABASE_URL=postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach
alembic upgrade head          # or: python -c "from vocal_coach.storage.migrate import upgrade_to_head as u; import os; u(os.environ['DATABASE_URL'])"
```

The migration URL is taken from `-x url=…`, then the programmatic `upgrade_to_head(url)` argument, then `DATABASE_URL`, then settings (`.env`), then `alembic.ini`. Run migrations once at startup from a single process (the compose entrypoint), not from every worker; `fail_stale_jobs` assumes a single backend process, and running it from several processes would fail jobs another process is still running.

**Summaries vs full rows.** `repo.list_analysis_summaries(user_id, limit=, offset=)` backs the analyses list: one query of scalar columns plus a few headline metrics extracted in SQL (JSON paths), with `has_transcript` / `has_coaching` flags; it never loads the metrics/transcript/coaching blobs. Load full rows only where they are shown or compared: `repo.get_analysis` for one, `repo.get_analyses(user_id, ids)` for a comparison (one scoped query, unknown or foreign ids dropped). For job progress, an SSE handler should open one short session per poll (or rely on `get_job`, which refreshes the row via `populate_existing`), never hold one session open for the whole stream.

**Duplicates.** Submitting the same file twice (two tabs, a double click) produces one row: `create_analysis` catches the unique-key violation, rolls back and returns the existing analysis. First login races in `upsert_user` resolve the same way. Every repository writer rolls the session back on failure, so the session stays usable.

Tests run the models on in-memory SQLite. `tests/test_migrations.py::test_upgrade_head_on_real_postgres` runs the migration against a throwaway Postgres container, round-trips data through the repository (JSONB, time zones, SQL `NULL`, cascades, summaries) and checks models and migration match; it is skipped when Docker is not installed.

Comparison (`vocal_coach/storage/comparison.py`) follows `config.yaml → comparison`: per metric path, `delta = last − first`, step deltas, arrow `↑ ↓ →`, verdict `improved / worsened / neutral / unchanged / unavailable`. `unchanged` means the change is below `min_meaningful_change_pct` of the first value. `delta` and the verdict span the first and last recordings that have the metric; a row with gaps is marked `partial: true`, and a metric present in fewer than two recordings is `unavailable`, never an error. Ties on `recorded_at` are ordered by id. Analyses with different `config_hash` or `analyser_version` are still compared, with `config_mismatch` / `analyser_version_mismatch: true`.

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
