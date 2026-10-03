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

Postgres via SQLAlchemy 2 + Alembic. Tables: `users`, `drive_connections`, `analyses` (unique on user + file hash + config hash), `jobs`. Every repository read is scoped by `user_id`; other users' rows read as missing.

```bash
export DATABASE_URL=postgresql+psycopg://vocal:vocal@localhost:5432/vocal_coach
alembic upgrade head          # or: python -c "from vocal_coach.storage.migrate import upgrade_to_head as u; import os; u(os.environ['DATABASE_URL'])"
```

Tests run the models on in-memory SQLite. `tests/test_migrations.py::test_upgrade_head_on_real_postgres` runs the migration against a throwaway Postgres container and is skipped when Docker is not installed.

Comparison (`vocal_coach/storage/comparison.py`) follows `config.yaml → comparison`: per metric path, `delta = last − first`, step deltas, arrow `↑ ↓ →`, verdict `improved / worsened / neutral / unchanged / unavailable`. `unchanged` means the change is below `min_meaningful_change_pct` of the first value. A metric missing in any recording yields `unavailable`, never an error. Analyses with different `config_hash` are still compared, with `config_mismatch: true`.
