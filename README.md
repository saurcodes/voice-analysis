# Vocal Coach

Vocal Coach measures a speaker's recordings and tells them what changed between takes. A user signs in, uploads an audio or video file (or picks one from their own Google Drive), and gets voice metrics, a transcript and, optionally, coaching text. Two or more recordings can be compared side by side.

It works on two separate paths:

1. **Deterministic metrics.** Signal analysis only (ffmpeg, praat-parselmouth, numpy, scipy), with every threshold in `backend/config.yaml`. The same file and the same config always give a byte-identical `metrics.json`. This path is the source of truth and the app is fully usable with nothing else.
2. **Optional LLM coaching.** The metrics, the faster-whisper transcript and the deltas against the previous recording go to an LLM (any OpenAI-compatible server such as Ollama, or Anthropic). The model interprets; it does not compute. Every number it cites is checked against the payload and any mismatch is shown as a warning.

Stack: React 19 + Vite frontend served by nginx, FastAPI backend with a process-pool job runner, Postgres, Keycloak for sign-in. Everything runs under `docker compose`.

## Prerequisites

- Docker with the compose plugin (Docker Desktop, Rancher Desktop, or Docker Engine on Linux). Give it at least 4 GB of memory: the backend image compiles praat-parselmouth on arm64 and the whisper model loads into the worker process.
- Free host ports 3000 (frontend), 8000 (backend), 8080 (Keycloak), 5432 (Postgres).
- `python3` on the host, used to generate keys and by `scripts/smoke.sh`.

Only for running parts of the stack outside Docker (see [Running in dev](#running-in-dev)):

- Python 3.12 and ffmpeg/ffprobe on `PATH` (`brew install ffmpeg` or `apt install ffmpeg`) for the backend.
- Node 22 and npm for the frontend.

Backend dependencies (`backend/pyproject.toml`): fastapi, uvicorn, sqlalchemy 2, alembic, psycopg, pydantic 2, pydantic-settings, PyJWT with cryptography, itsdangerous, cryptography (Fernet), praat-parselmouth, numpy, scipy, faster-whisper, pyyaml, httpx, anthropic, sse-starlette, python-multipart; dev extras pytest, pytest-httpx, testcontainers. The OpenAI-compatible provider and the Google Drive client talk HTTP through `httpx`; there is no `openai` or Google client SDK. `backend/requirements.lock` pins the exact versions the determinism guarantee was verified with.

## Quick start

```bash
cp .env.example .env
```

Generate the two keys. `SECRET_KEY` signs the Google OAuth state; `DRIVE_TOKEN_KEY` encrypts stored Drive refresh tokens. Both only matter once Google Drive is configured, but generating them now means you will not have to come back:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Put the first value in `.env` as `SECRET_KEY=...` (uncomment the line) and the second as `DRIVE_TOKEN_KEY=...`. The second command produces a standard Fernet key, the same format as `backend/.venv/bin/python -c "from vocal_coach.drive.crypto import generate_key; print(generate_key())"`.

Build and start the stack:

```bash
docker compose up -d --build
```

A cold build takes a few minutes (the backend compiles praat-parselmouth on arm64). Check that all four services are up with `docker compose ps`; Keycloak takes about 30 seconds to report healthy and the backend waits for it.

Open http://localhost:3000 and sign in as `demo` / `demo`. That user comes from the dev realm (`keycloak/realm-export.dev.json`), which is the default. Click "Analyse", drop an audio or video file (`m4a`, `mp3`, `wav`, `mov`, `mp4`, up to 500 MB), and watch the job progress. The first job downloads the whisper `small` model (about 460 MB) into the `models` volume, so it takes longer than later ones.

Coaching shows as enabled (`config.yaml` ships `llm.enabled: true`), but the "Coaching provider is unavailable right now" message stays until an LLM is reachable; see [LLM coaching](#llm-coaching). Metrics and transcripts work without it.

To check the whole stack from the command line:

```bash
./scripts/smoke.sh
```

It runs `docker compose up -d --build` (skip with `SMOKE_NO_UP=1`), gets a token for `demo`, calls `/api/me`, uploads a generated 3-second sine WAV, polls the job until it finishes, fetches the analysis, compares the two newest analyses when there are two, and prints `/api/llm/models`. It exits non-zero on any failed step. A 503 from `/api/llm/models` (no LLM reachable) is printed, not treated as a failure. Set `SMOKE_TIMEOUT_S` above the default 180 if the first run is still downloading the whisper model.

Stop the stack with `docker compose down`. `docker compose down -v` also deletes the volumes: the database (analyses, users, the Keycloak realm), uploads, the Drive cache and the whisper model.

## First run with Keycloak

Keycloak runs in the `keycloak` service (`start-dev --import-realm`) and keeps its data in its own `keycloak` database inside the Postgres volume. On first start it imports the realm file named by `KEYCLOAK_REALM_FILE`:

- `keycloak/realm-export.dev.json` (default): realm `vocal-coach`, public client `vocal-coach-web` with PKCE, the `user` role, user `demo` / `demo`, self-registration on, and the password grant enabled (`scripts/smoke.sh` and the Playwright suite need it).
- `keycloak/realm-export.json`: same realm, client, audience mapper and role, but no users, no password grant and no self-registration. Use it for anything shared.

Both files allow `http://localhost:3000/*` and `http://localhost:5173/*` as redirect URIs.

**Creating a real user.** Open the admin console at http://localhost:8080/admin and sign in with `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` from `.env` (`admin` / `admin` by default). Switch to the `vocal-coach` realm, then Users > Add user: set a username and an email (the app shows the email in Settings), save, open the Credentials tab and set a password with "Temporary" off. The backend checks the token's issuer and audience, not roles, so no role mapping is needed (the realm still defines a `user` role for later use). Sign in at http://localhost:3000 with the new account.

**Switching to the production realm.** Set `KEYCLOAK_REALM_FILE=./keycloak/realm-export.json` in `.env`. `--import-realm` only imports a realm that does not exist yet, so an existing `vocal-coach` realm is never replaced. Either:

- delete the realm in the admin console (realm settings, Action > Delete), then `docker compose up -d keycloak` to recreate the container and import the new file; or
- start from fresh volumes with `docker compose down -v` and `docker compose up -d --build` (this also deletes every analysis).

The same rule applies to any edit to a realm file: a running stack keeps the realm it imported. Make the change in the admin console, or re-import as above.

Change `KEYCLOAK_ADMIN_PASSWORD` before exposing Keycloak beyond your machine. The bootstrap admin is created on the first start only, so after that change the password in the admin console.

## LLM coaching

Server-wide settings live in the `llm` section of `backend/config.yaml`:

| Key | Shipped value | Meaning |
|---|---|---|
| `enabled` | `true` | Master switch for the coach stage, `/api/llm/models` and re-run coaching. |
| `provider` | `openai_compatible` | `openai_compatible` or `anthropic`. |
| `base_url` | `http://localhost:11434/v1` | OpenAI-compatible server URL; ignored by `anthropic`. |
| `model` | `""` | Default model. Empty with `openai_compatible` means the user must pick one; empty with `anthropic` means `claude-opus-5-5`. |
| `allowed_models` | `[]` | Non-empty limits both the model list and what a request may ask for. |
| `seed` | `42` | Sent to OpenAI-compatible servers. |
| `timeout_s` | `120` | Read timeout of one provider call. |
| `max_transcript_words` | `1500` | Transcript words sent to the model. |

`config.yaml` is copied into the backend image, so after editing it run `docker compose up -d --build backend`. The `llm` section is not part of `config_hash`, so changing it never invalidates stored analyses. API keys come only from the environment, never from `config.yaml`. The full provider behaviour is in [backend/README.md, "LLM coaching"](backend/README.md#llm-coaching-plan-6).

**Ollama (local, free).** Install Ollama and pull a model, for example `ollama pull llama3.2`. Ollama listens on `127.0.0.1` by default, which the backend container cannot reach. Make it listen on all interfaces:

- macOS app: `launchctl setenv OLLAMA_HOST 0.0.0.0`, then quit and restart Ollama.
- Linux: run `OLLAMA_HOST=0.0.0.0 ollama serve`, or set `Environment="OLLAMA_HOST=0.0.0.0"` in a systemd override for the `ollama` service.

This exposes Ollama's unauthenticated API to your network; block port 11434 in your firewall or bind it to the Docker bridge address instead. Compose already points the backend at the host with `LLM_BASE_URL_OVERRIDE=http://host.docker.internal:11434/v1` (leave that line commented out in `.env` to keep the default; an empty value disables the override). Under Rancher Desktop set `LLM_BASE_URL_OVERRIDE=http://host.rancher-desktop.internal:11434/v1` and run `docker compose up -d backend`. Check it with `curl -s http://localhost:8000/api/llm/models -H "Authorization: Bearer <token>"` or by opening the Analyse drawer: the model list fills in when the server answers.

**Anthropic.** Set `ANTHROPIC_API_KEY=...` in `.env`, set `provider: anthropic` in `backend/config.yaml` (optionally `model`), then `docker compose up -d --build backend`. A missing key is reported as a coaching warning, not a crash.

**Other OpenAI-compatible servers** (vLLM, LM Studio, a hosted endpoint): set `base_url` in `config.yaml` or `LLM_BASE_URL_OVERRIDE` in `.env`, and `OPENAI_COMPAT_API_KEY` if the server needs a bearer token.

**In the UI.** The Analyse drawer has a coaching switch and a model picker filled from `GET /api/llm/models`; both stay disabled with "Coaching provider is unavailable right now" while the provider does not answer. On an analysis, the Coaching tab shows the result, any number or markup check warnings, and a "Re-run coaching" button that takes a new speaker context and model. Coaching never fails a job: a provider error ends as a warning and the analysis is still stored.

## Google Drive

Optional. Each signed-in user can link their own Google Drive (read-only) and analyse files from it without uploading. You need an OAuth 2.0 "Web application" client from the Google Cloud Console with the Drive API enabled and `http://localhost:3000/api/drive/callback` as an authorised redirect URI. Put `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SECRET_KEY` and `DRIVE_TOKEN_KEY` in `.env`, then `docker compose up -d backend`. With all three of the client id, secret and `DRIVE_TOKEN_KEY` set, the backend refuses to start unless `SECRET_KEY` is random and at least 32 characters. Users then link Drive from Settings.

The full setup (consent screen test users, redirect URI rules, endpoints, cache layout and size cap, troubleshooting) is in [backend/README.md, "Google Drive"](backend/README.md#google-drive-plan-7).

## Running in dev

Run Postgres and Keycloak in Docker and the backend and frontend on the host, with hot reload.

```bash
docker compose up -d postgres keycloak
```

Backend, from `backend/` (Python 3.12, ffmpeg on `PATH`):

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
set -a; . ../.env; set +a
export FRONTEND_ORIGIN=http://localhost:5173
.venv/bin/uvicorn "vocal_coach.main:create_app" --factory --reload
```

The backend reads `.env` from its working directory; sourcing the root `.env` as above gives it the same values (`DATABASE_URL` points at `localhost:5432`, `DATA_DIR=data` resolves to `backend/data/`). The app applies Alembic migrations on startup. It listens on http://localhost:8000; the API docs are at http://localhost:8000/docs. For Google Drive in this mode, register `http://localhost:8000/api/drive/callback` in Google Cloud (the bare default of `GOOGLE_REDIRECT_URI`). The backend can also run alone on the command line: `.venv/bin/python -m vocal_coach.analysis.analyser path/to/recording.m4a --out data/metrics.json`.

Frontend, from `frontend/` (Node 22):

```bash
npm install
npm run dev
```

It serves http://localhost:5173. `vite.config.ts` proxies `/api` to `http://localhost:8000`, and Keycloak settings come from the static `frontend/public/config.json` (`http://localhost:8080`, realm `vocal-coach`, client `vocal-coach-web`; edit it for another Keycloak). To develop only the frontend, run the backend in Docker instead: `docker compose up -d postgres keycloak backend`.

After any API change, regenerate the frontend types: `.venv/bin/python scripts/export_openapi.py` from `backend/` (writes `backend/openapi.json`), then `npm run gen:api` from `frontend/`.

## Tests

Backend, from `backend/`:

```bash
.venv/bin/python -m pytest -W error
```

Tests are offline: synthetic audio, in-memory SQLite, `pytest-httpx` for Google and LLM HTTP, a test RSA key for JWTs. Tests that need ffmpeg are skipped when it is missing. `tests/test_migrations.py` and `tests/test_storage_roundtrip.py` start a throwaway Postgres with testcontainers and are skipped when `docker` is not on `PATH`. They default `TESTCONTAINERS_RYUK_DISABLED=true` because Rancher Desktop's user-mode networking cannot start the ryuk reaper; on Docker Desktop you can export `TESTCONTAINERS_RYUK_DISABLED=false` to get automatic container cleanup. To run the real whisper model once: `VOCAL_COACH_REAL_WHISPER=1 .venv/bin/python -m pytest tests/test_transcription_run.py`.

Frontend unit tests, from `frontend/` (Vitest, React Testing Library, MSW; no network):

```bash
npm test
npm run lint
npm run build
```

End-to-end tests (Playwright) drive a real browser against the running compose stack: Keycloak login, the Library, an analysis page and Settings. They are not part of `npm test`.

```bash
docker compose up -d --build
cd frontend
npm run e2e:install
npm run e2e
```

`npm run e2e:install` downloads Chromium once per machine. `E2E_BASE_URL` (default `http://localhost:3000`), `E2E_USER` / `E2E_PASSWORD` (default `demo` / `demo`) and `E2E_USER_EMAIL` (default `demo@example.test`) adjust the target; see [frontend/e2e/README.md](frontend/e2e/README.md).

Stack smoke test: `./scripts/smoke.sh` (see [Quick start](#quick-start)).

## Configuration reference

All keys are read from `.env` by `docker compose` (variable substitution) and, for a backend run on the host, by the backend itself. "Compose default" is the value `docker-compose.yml` uses when the key is unset; "bare default" is the backend's own default in `backend/vocal_coach/settings.py`.

| Key | Default | Used by | Notes |
|---|---|---|---|
| `POSTGRES_USER` | `vocal` | postgres, keycloak, backend (compose) | Compose builds the backend's `DATABASE_URL` and Keycloak's DB login from it. |
| `POSTGRES_PASSWORD` | `vocal` | postgres, keycloak, backend (compose) | Same. |
| `KEYCLOAK_ADMIN` | `admin` | keycloak | Bootstrap admin, created on first start only. |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin` | keycloak | Change for anything shared; later changes go through the admin console. |
| `KEYCLOAK_REALM_FILE` | `./keycloak/realm-export.dev.json` | keycloak | Realm imported on first start; `./keycloak/realm-export.json` for production. |
| `KEYCLOAK_ISSUER` | `http://localhost:8080/realms/vocal-coach` | backend | Must equal the token's `iss`, i.e. the realm URL as the browser sees it. |
| `KEYCLOAK_AUDIENCE` | `vocal-coach-web` | backend | Required `aud` claim (added by the realm's audience mapper). |
| `KEYCLOAK_JWKS_URL_OVERRIDE` | compose: `http://keycloak:8080/realms/vocal-coach/protocol/openid-connect/certs`; bare: unset | backend | Where the backend fetches signing keys. Fixed in `docker-compose.yml`, not read from `.env`; bare default derives it from the issuer. |
| `DATABASE_URL` | compose: built from `POSTGRES_*`; bare: `postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach` | backend, alembic | The `.env` value only matters for a backend on the host. |
| `FRONTEND_ORIGIN` | compose: `http://localhost:3000`; bare: `http://localhost:5173` | backend | Target of the Drive callback redirect; `https` turns on the `Secure` cookie flag. |
| `DATA_DIR` | compose: `/data` (volume `appdata`); bare: `data` | backend | Uploads and the Drive cache. Fixed to `/data` in compose. |
| `JOB_WORKERS` | `1` | backend | Job worker processes; each loads its own whisper model. |
| `MAX_UPLOAD_MB` | `500` | backend | Upload cap; larger uploads get 413. nginx allows bodies up to 600 MB. |
| `CACHE_MAX_MB` | `2048` | backend | Total Drive cache cap; least recently used files are evicted first. Not forwarded by `docker-compose.yml`. |
| `DRIVE_MAX_MB` | value of `MAX_UPLOAD_MB` | backend | Drive download cap. Not forwarded by `docker-compose.yml`. |
| `REQUIRE_FFMPEG` | `true` | backend | Startup fails if ffmpeg is missing. Set `false` only for API work on a host without ffmpeg. Not forwarded by `docker-compose.yml`. |
| `OPENAI_COMPAT_API_KEY` | empty | backend | Optional bearer token for the `openai_compatible` provider. |
| `ANTHROPIC_API_KEY` | empty | backend | Required when `llm.provider` is `anthropic`. |
| `LLM_BASE_URL_OVERRIDE` | compose: `http://host.docker.internal:11434/v1`; bare: unset | backend | Replaces `llm.base_url`. Present but empty disables the compose default. |
| `SECRET_KEY` | `dev-secret-change-me` | backend | Signs the Drive OAuth state. Must be random and 32+ characters once Drive is configured. |
| `DRIVE_TOKEN_KEY` | empty | backend | Fernet key encrypting Drive refresh tokens; validated at startup when Drive is configured. |
| `GOOGLE_CLIENT_ID` | empty | backend | OAuth web client id. Drive is configured when this, the secret and `DRIVE_TOKEN_KEY` are all set. |
| `GOOGLE_CLIENT_SECRET` | empty | backend | Secret for the client above. |
| `GOOGLE_REDIRECT_URI` | compose: `http://localhost:3000/api/drive/callback`; bare: `http://localhost:8000/api/drive/callback` | backend | Must match the Google Cloud Console entry exactly. |
| `KEYCLOAK_URL` | `http://localhost:8080` | frontend container | Written into the runtime `/config.json` and the CSP at container start. |
| `KEYCLOAK_REALM` | `vocal-coach` | frontend container | Same. |
| `KEYCLOAK_CLIENT_ID` | `vocal-coach-web` | frontend container | Same. |

Keys marked "not forwarded by `docker-compose.yml`" take effect for a backend run on the host; to use them under compose, add them to the `backend` service's `environment` block.

Test and script variables (not in `.env`): `TESTCONTAINERS_RYUK_DISABLED` and `VOCAL_COACH_REAL_WHISPER` (backend tests), `E2E_BASE_URL`, `E2E_USER`, `E2E_PASSWORD`, `E2E_USER_EMAIL` (Playwright), `SMOKE_NO_UP`, `SMOKE_TIMEOUT_S`, `API_URL`, `KEYCLOAK_URL`, `SMOKE_USER`, `SMOKE_PASSWORD` (`scripts/smoke.sh`).

Analysis thresholds, transcription settings, comparison direction rules and LLM settings are in `backend/config.yaml`, not in the environment. Changing anything under `analysis` or `articulation` changes `config_hash`, and the Compare page flags recordings analysed with different hashes.

## Troubleshooting

- **Port already in use** (`Bind for 0.0.0.0:5432 failed`): another Postgres, Keycloak or dev server holds 5432, 8080, 8000 or 3000. Stop it (`lsof -i :5432` shows the process), or change the left side of that service's `ports:` mapping in `docker-compose.yml`. Moving Keycloak off 8080 also means changing `KEYCLOAK_ISSUER` and `KEYCLOAK_URL`.
- **Rancher Desktop: the backend cannot reach a host service.** `host.docker.internal` via `host-gateway` may not resolve; use `host.rancher-desktop.internal`, for example `LLM_BASE_URL_OVERRIDE=http://host.rancher-desktop.internal:11434/v1`, then `docker compose up -d backend`.
- **Rancher Desktop: testcontainers hangs or fails on ryuk.** The reaper cannot start under user-mode networking. The Docker-gated tests already default `TESTCONTAINERS_RYUK_DISABLED=true`; make sure it is not exported as `false` in your shell. Without the reaper, a crashed test run can leave a `postgres` container behind; remove it with `docker ps` and `docker rm -f`.
- **Keycloak "Invalid parameter: redirect_uri" or sign-out fails after editing a realm file.** The running realm was imported before your edit and is never re-imported. Edit the client in the admin console (realm `vocal-coach`, Clients > `vocal-coach-web`: "Valid redirect URIs", "Valid post logout redirect URIs", "Web origins"), or delete the realm and recreate the container as in [First run with Keycloak](#first-run-with-keycloak). Also check that `KEYCLOAK_URL` and `KEYCLOAK_ISSUER` use the same host the browser uses.
- **Every API call is 401.** The token's issuer or audience does not match `KEYCLOAK_ISSUER` / `KEYCLOAK_AUDIENCE`, usually because the browser reached Keycloak under a different host name than the one in `KEYCLOAK_ISSUER` (for example `127.0.0.1:8080` instead of `localhost:8080`). Use the same host everywhere: `KEYCLOAK_URL`, `KEYCLOAK_ISSUER` and the address you open in the browser.
- **"Coaching provider is unavailable right now" / `/api/llm/models` returns 503.** The backend container cannot reach the LLM. For Ollama: confirm `OLLAMA_HOST=0.0.0.0` took effect (`lsof -i :11434` should show `*:11434`, not `localhost:11434`), that `.env` does not set `LLM_BASE_URL_OVERRIDE=` to an empty value, and test from inside the container with `docker compose exec backend python -c "import httpx; print(httpx.get('http://host.docker.internal:11434/v1/models').status_code)"`.
- **Backend image build fails or is slow on arm64 (Apple silicon).** praat-parselmouth has no linux/aarch64 wheel, so the `wheels` stage of `backend/Dockerfile` compiles it with build-essential and ninja. A cold build takes a few minutes; an out-of-memory failure (`Killed`, exit 137) means Docker needs more memory (4 GB or more). Later builds reuse the cached layer.
- **The first analysis sits in "transcribe" for minutes.** The worker is downloading the whisper `small` model (about 460 MB) into the `models` volume. It is downloaded once.
- **The backend exits at startup with a Drive settings error.** Drive is configured (client id, secret and `DRIVE_TOKEN_KEY` all set) and `SECRET_KEY` is missing, the dev default or shorter than 32 characters, or `DRIVE_TOKEN_KEY` is not a Fernet key. Regenerate with the commands in [Quick start](#quick-start).

## Architecture

```
voice-analysis/
├── docker-compose.yml        postgres, keycloak, backend, frontend
├── .env.example              every configuration key, grouped and commented
├── scripts/smoke.sh          end-to-end check against the compose stack
├── deploy/postgres-init/     creates the keycloak database
├── keycloak/                 realm-export.dev.json (demo user), realm-export.json (production)
├── backend/                  FastAPI service, Python 3.12
│   ├── config.yaml           analysis thresholds, transcription, comparison rules, llm
│   ├── alembic/              database migrations
│   ├── vocal_coach/
│   │   ├── analysis/         deterministic metrics (pitch, phrasing, pace, intonation, energy, ...)
│   │   ├── transcription/    faster-whisper, fillers, syllables, clarity
│   │   ├── storage/          SQLAlchemy models, repository, comparison
│   │   ├── auth/             Keycloak JWT verification
│   │   ├── api/              routers under /api
│   │   ├── jobs/             process-pool runner, SSE progress
│   │   ├── drive/            per-user Google OAuth, Drive client, cache
│   │   ├── llm/              provider registry, coach, number and markup checks
│   │   └── pipeline.py       download, extract, analyse, transcribe, coach
│   └── tests/
├── frontend/                 React 19 + Vite + TypeScript, served by nginx
│   ├── src/                  pages, components, API and SSE clients, auth
│   ├── e2e/                  Playwright suite (npm run e2e)
│   ├── public/config.json    Keycloak settings for the dev server
│   └── nginx.conf.template   SPA fallback, /api proxy, security headers
└── docs/superpowers/         design spec and implementation plans
```

Request flow: the browser signs in to Keycloak with Authorization Code + PKCE and sends the access token as a Bearer header on every `/api` call, which nginx proxies to the backend. The backend verifies the token against Keycloak's signing keys, upserts the user, and scopes every query to that user. An upload or Drive selection creates a job row and hands it to a worker process, which downloads or reads the file, extracts a 16 kHz WAV with ffmpeg, computes the metrics, transcribes, stores the analysis in Postgres and then runs coaching if requested. Progress is written to the job row and streamed to the browser over Server-Sent Events (`GET /api/jobs/{id}/events`), with polling as the fallback. The analysis page, the Library and the Compare page read stored analyses and comparison deltas; the LLM is only called by the coach stage and by "Re-run coaching".

Further reading:

- [backend/README.md](backend/README.md): backend module reference (metrics, transcription, storage, API and jobs, LLM providers, Google Drive).
- [frontend/README.md](frontend/README.md): frontend module reference (dev loop, design tokens, SSE client, nginx image).
- [Design spec](docs/superpowers/specs/2026-10-03-vocal-coach-design.md), with the amendments made during implementation in §20.
- Implementation plans, in build order: [1 analysis core](docs/superpowers/plans/2026-10-03-plan-1-analysis-core.md), [2 transcription](docs/superpowers/plans/2026-10-03-plan-2-transcription.md), [3 storage and comparison](docs/superpowers/plans/2026-10-03-plan-3-storage-comparison.md), [4 API, auth and jobs](docs/superpowers/plans/2026-10-04-plan-4-api-auth-jobs.md), [5 React UI](docs/superpowers/plans/2026-10-04-plan-5-react-ui.md), [6 LLM coaching](docs/superpowers/plans/2026-10-04-plan-6-llm-coaching.md), [7 Google Drive](docs/superpowers/plans/2026-10-04-plan-7-drive-oauth.md), [8 README and hardening](docs/superpowers/plans/2026-10-05-plan-8-readme-hardening.md).
