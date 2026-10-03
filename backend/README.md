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
