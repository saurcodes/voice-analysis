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
docker compose up -d --build       # postgres + keycloak (dev realm imported, user demo/demo) + backend
./scripts/smoke.sh path/to/recording.wav   # token → /api/me → upload → SSE progress
```

The backend image is a multi-stage build: there is no aarch64 wheel for praat-parselmouth, so on arm64 (Apple
silicon) the builder stage compiles it. A cold build takes about 2.5 minutes; later builds reuse the layer cache.
The first job downloads the whisper model (~460 MB) into the `models` volume.

**Realm files.** `keycloak/realm-export.dev.json` (default; `KEYCLOAK_REALM_FILE` in `.env`) has the `demo`/`demo` user,
the password grant and self-registration — `scripts/smoke.sh` needs it. `keycloak/realm-export.json` is
production-shaped: no users, no password grant, no self-registration; same client, PKCE, audience mapper and `user`
role. Keycloak imports the realm only when it does not exist yet, so switching files needs a fresh Keycloak database.

Dev loop: `docker compose up -d postgres keycloak`, then from `backend/`:
`DATABASE_URL=postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach uvicorn "vocal_coach.main:create_app" --factory --reload`.
Migrations run once in the container entrypoint; with `--reload` locally run `alembic upgrade head` yourself.

Auth: Bearer tokens from Keycloak realm `vocal-coach`, client `vocal-coach-web` (public, PKCE). The realm export adds an
audience mapper so access tokens carry `aud: vocal-coach-web`; without it Keycloak only emits `aud: account` and the API
answers 401. `directAccessGrantsEnabled` is on only in the dev realm, so `scripts/smoke.sh` can use the password grant.

Upload: `POST /api/analyses` multipart with `file` (required), `speaker_context`, `llm_enabled`, `llm_model`, and
`recorded_at` (ISO-8601 with a timezone offset, e.g. `2026-09-30T08:15:00+02:00`; defaults to the upload time; a naive or
unparsable value is 422). The stored file name drops any client-side directories.

Jobs run in a spawn-based process pool (`JOB_WORKERS`, default 1): praat-parselmouth and CTranslate2 are not safe to share
across threads, and each worker loads the whisper model once. Progress is written to the `jobs` row and streamed by
`GET /api/jobs/{id}/events`. On restart, unfinished jobs are marked `failed / server restarted`. Run exactly one backend
process per database (the restart sweep is not multi-process safe).

Endpoints: see `/docs`. Drive (`/api/drive/*`, `source: "drive"`) is a stub until Plan 7. Coaching
(`/api/analyses/{id}/coach`, `/api/llm/models`, `/api/me`'s `llm_enabled`/`llm_provider`) is wired up; see
"LLM coaching" below.

Jobs: `GET /api/jobs?status=` lists jobs newest first; `POST /api/jobs/{id}/retry` re-runs a finished job's upload (410
once the upload has been cleaned up). A worker process that dies (OOM kill, segfault) fails its job with
`worker crashed: …` and the pool is rebuilt; if that fails the upload answers 503. Uploads live in
`DATA_DIR/uploads/<user>/<source_sha256>.<ext>` and are deleted once no analysis and no unfinished job references them
(after the last analysis is deleted, or after a pipeline failure).

### Notes for Plan 5 (frontend)

- SSE needs a fetch-based client (e.g. `@microsoft/fetch-event-source`): native `EventSource` cannot send an
  `Authorization` header. Access tokens expire after 300 s, so a reconnect must use a fresh token.
- Not every stage event is guaranteed: a fast job can move through several stages between two 500 ms polls, so
  the client sees only the latest. A dedupe hit goes `download → extract → done`. Treat `done`, `error` and `timeout`
  as terminal; after `timeout`, poll `GET /api/jobs/{id}`.
- Error bodies are `{"detail": str}`, except FastAPI's 422 validation errors, where `detail` is a list of objects.
- The OpenAPI schema types the analysis detail (`MetricsReport`, `Transcript`), `/config/public` (`PublicConfig`),
  `/llm/models` (`LlmModels`), job status/stage enums, and the multipart upload body.

### Known gaps

- Retry re-uses `file_name`, the upload and `recorded_at`, but not `speaker_context` or the LLM options.
- Multipart uploads are buffered to a spooled temp file by Starlette before the size backstop runs (Plan 8).

## Frontend (Plan 5)

The React UI lives in `frontend/`; see `frontend/README.md` for the dev loop, tests, regenerating
API types, design tokens, chart colors and the SSE client. `docker compose up -d --build` (above)
also builds and starts it as the `frontend` service, served by nginx on `http://localhost:3000`.

## LLM coaching (Plan 6)

Deterministic metrics and the transcript become coaching JSON (`what_improved`, `what_is_lacking`,
`next_steps`, `marked_up_example`) through a provider-agnostic `vocal_coach/llm/` package. Coaching
never fails a job or a request: a provider error, a timeout, invalid model output or a missing key
always ends as `coaching: null` plus one or more `coaching_warnings`, and the pipeline still reaches
`done`.

### Config (`config.yaml`'s `llm` section)

```yaml
llm:
  enabled: true                       # master switch; false disables /llm/models, POST /coach and
                                       # the pipeline's coach stage without touching anything else
  provider: openai_compatible         # or "anthropic"
  base_url: http://localhost:11434/v1 # openai_compatible only; ignored by anthropic
  model: ""                           # default model; empty + openai_compatible = no default (a
                                       # model must be requested); empty + anthropic defaults to
                                       # claude-opus-5-5
  allowed_models: []                  # non-empty allow-lists both /llm/models and the model a
                                       # caller may request; anything else is rejected
  seed: 42
  timeout_s: 120                      # read timeout of one provider call; also the deadline after
                                       # which an invalid first answer is not retried
  max_output_tokens: 2048             # anthropic raises this to a floor of 16000 (see Providers)
  max_transcript_words: 1500          # the transcript sent to the model is cut to this many words
```

`llm` is not part of `config_hash` (only `analysis` and `articulation` are), so changing it never
invalidates stored analyses or re-triggers the dedupe check.

### Keys and environment

API keys are never read from `config.yaml` or accepted over the API; they come only from the
process environment:

- `OPENAI_COMPAT_API_KEY`: optional bearer token sent to the `openai_compatible` provider (omitted
  entirely when unset, which is normal for a local, unauthenticated server such as Ollama).
- `ANTHROPIC_API_KEY`: required by the `anthropic` provider; its absence is a clean
  `coaching failed: ANTHROPIC_API_KEY is not set` warning, not a crash.
- `LLM_BASE_URL_OVERRIDE`: swaps `llm.base_url` for one value at the process level, for a
  container that cannot resolve `localhost`. Compose sets this to
  `http://host.docker.internal:11434/v1` by default (with `extra_hosts: host-gateway` on the
  backend service) so a backend running in Docker can reach an Ollama running on the host. Set
  `LLM_BASE_URL_OVERRIDE=` (present but empty) in `.env` to disable the override under compose and
  use `config.yaml`'s `base_url` as-is: compose's default only applies when the variable is unset
  entirely, not when it is set to an empty value.

### Providers

- **`openai_compatible`** talks to any server exposing the OpenAI chat-completions wire format
  (Ollama's OpenAI-compatible endpoint, vLLM, LM Studio and others) over `httpx`. It tries strict
  structured output (`response_format: json_schema`) first and falls back once, only on a 400 or
  422, to `response_format: json_object` with the schema spelled out in the system prompt; 401, 403,
  404, 429 and 5xx fail immediately. Parsing tolerates a `<think>...</think>` block, a Markdown code
  fence and prose around the JSON object; `finish_reason: "length"` is reported as a truncated
  response. Connect timeout is 10 s; read timeout is `timeout_s`; `GET /models` uses 10 s overall.
- **`anthropic`** uses the official SDK's structured outputs (`output_config.format`) instead of a
  forced tool choice, and never sets `temperature`: current Claude models reject both with HTTP 400.
  Determinism comes from the strict schema, the fixed prompt and the post-checks below. It sends
  `output_config.effort: "low"` (coaching is a short structured summary; higher effort only adds
  latency) and `max_tokens = max(max_output_tokens, 16000)`, because thinking tokens count against
  `max_tokens` and a lower budget truncates the answer. Generation runs with SDK retries disabled
  (coaching degrades to a warning instead of doubling the wait); model listing keeps the SDK
  default retries with a 10 s timeout.

**Pointing at a local Ollama:** run `ollama serve` and pull a model, then set
`llm.base_url: http://localhost:11434/v1` (the default) for a backend running directly on the host,
or rely on compose's `LLM_BASE_URL_OVERRIDE` default for a backend running in a container. Either
way, `provider: openai_compatible` and `model` (or `allowed_models`) name the pulled model.

**Ollama and a containerised backend:** Ollama listens on `127.0.0.1` by default, which a container
cannot reach through `host.docker.internal`. Make it listen on all interfaces with
`OLLAMA_HOST=0.0.0.0` (on macOS: `launchctl setenv OLLAMA_HOST 0.0.0.0`, then quit and restart the
Ollama app). Warning: this exposes Ollama's unauthenticated API to your whole LAN. Block port 11434
in your firewall, or bind it to the Docker bridge IP only instead of `0.0.0.0`. Under Rancher
Desktop the host alias is `host.rancher-desktop.internal`: set
`LLM_BASE_URL_OVERRIDE=http://host.rancher-desktop.internal:11434/v1`.

### Payload, post-checks and degrade behaviour

The payload sent to a provider drops `per_phrase`, `per_phrase_end_drop_db` and the transcript's
`words`/`segments`; it caps `long_pauses`, `eaten_words`, `rushed_runs` and `low_conf_words` to 20
items each; it replaces `metrics.timeline` (one entry per window) with `metrics.timeline_summary`
(`window_s`, `window_count`, and min/p50/max of `f0_median_hz`, `f0_sd_st` and
`intensity_median_db` over non-null windows); it cuts the transcript text to
`max_transcript_words` words, with `transcript_truncated` and `transcript_word_count` (the full
count) always present; and it includes a `comparison` block (deltas vs. the user's previous
analysis by `recorded_at`, or `null` when none exists).

Two checks run on every answer and add to `coaching_warnings` without ever discarding the stored
coaching JSON:

- **Number check**: every number the model cites in `what_improved`, `what_is_lacking` or
  `next_steps` must trace back to a numeric value in the payload (as serialised, or rendered at 0 to
  6 decimals, with thousands separators for integers; a negative delta may be cited unsigned), to a
  number in the transcript or the system prompt, or be a small count from 0 to 10. A re-rounding is
  accepted; an invented number is flagged. `marked_up_example` is covered by the markup check.
- **Markup check**: `marked_up_example`, with `//`/`↘` marks removed and punctuation stripped, must
  be a contiguous word subsequence of the transcript. With no transcript available, the check is
  skipped with a `"no transcript available for marked_up_example"` warning instead of failing.

A model's first answer that fails schema validation is retried once with the validation error
attached (cut to 500 characters; no retry once the first call has taken longer than `timeout_s`);
a second failure (or any provider exception: network, auth, HTTP status, timeout) stores
`coaching: null` and a readable warning, never a stack trace or a URL carrying a key.

### Endpoints

- `GET /api/llm/models` → `{enabled, provider, models}`. `enabled: false` short-circuits to
  `{enabled: false, provider: null, models: []}` without calling the provider; a provider that
  cannot list models answers `503`.
- `GET /api/me` → `llm_enabled` and `llm_provider` (`null` when disabled) mirror `config.yaml`.
- `POST /api/analyses/{id}/coach` (body: `{speaker_context?, model?}`, `speaker_context` at most 2000
  characters, the same limit as the upload form field) re-runs coaching synchronously
  and returns the updated analysis detail. `404` when the analysis does not exist, `503` when
  coaching is disabled, `422` when the requested (or configured) model is rejected by a non-empty
  `allowed_models`, or when no model is requested or configured and the provider is not `anthropic`
  (no default model to fall back to).
