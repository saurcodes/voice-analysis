# Vocal Coach — Plan 1: Analysis Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic signal-analysis engine: a WAV in, a byte-identical `metrics.json` out, every run.

**Architecture:** A `backend/vocal_coach` Python package. `analysis/audio.py` normalises any input to mono 16 kHz WAV via ffmpeg. `analysis/tracks.py` extracts the shared F0 and intensity contours once with praat-parselmouth. Each metric module (`pitch`, `phrasing`, `pace`, `intonation`, `energy`, `voice_quality`, `articulation`, `timeline`) is one file with one public `compute(...)` returning a pydantic block. `analysis/analyser.py` wires them into a `MetricsReport` and `analysis/serialise.py` produces canonical JSON. No module reads config except through `config.py`.

**Tech Stack:** Python 3.11+, praat-parselmouth, numpy, scipy, pydantic 2, pyyaml, pytest, ffmpeg/ffprobe (system binaries).

**Spec:** `docs/superpowers/specs/2026-10-03-vocal-coach-design.md` (this plan implements §3.1 backend analysis paths, §6, and the analysis rows of §16; later plans cover §7–§15).

## Global Constraints

- Python ≥ 3.11. Package lives at `backend/vocal_coach`; tests at `backend/tests`; run everything from `backend/`.
- All analysis parameters come from `backend/config.yaml` sections `analysis` and `articulation`, exactly the values in spec §6.2. No numeric threshold may appear as a literal inside an `analysis/*.py` module.
- No randomness anywhere in `analysis/`. Test fixtures that need noise use `numpy.random.default_rng(0)`.
- `config_hash = "sha256:" + sha256(canonical JSON of analysis + articulation sections)`.
- `metrics.json` serialisation: floats rounded to 4 decimals, except ratio-type fields (`voiced_fraction`, `creak_fraction_below_100hz`, `jitter_local`, `shimmer_local`, `modulation_depth`, `weak_peak_fraction`) at 6 decimals; NaN/inf become `null`; `json.dumps(sort_keys=True, separators=(",", ":"))`.
- `schema_version = "1.0"`, `ANALYSER_VERSION = "0.1.0"`.
- Audio extraction command is exactly `ffmpeg -y -i <in> -vn -ac 1 -ar 16000 -sample_fmt s16 -f wav <out>`; `content_sha256` is over the resulting WAV bytes.
- Commit after every task with the message given in the task. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **Audio with no voiced speech** (silence, music, noise): the analyser must return a report with `recording_quality.reasons` containing `"no_voiced_speech"` and `null` pitch fields, never raise. Test added to Task 12.
2. **Long leading silence** (> 5 s before first word): `opening_f0_median_hz` and `opening_vs_overall_st` must be `null`, not NaN or a crash. Test added to Task 4.
3. **Phrase shorter than the intonation tail** (< 80 ms, or no voiced frames in the tail): counted in `unclassified_count`, not forced into `flat`. Test added to Task 7.
4. **Recording shorter than two energy windows** (< 30 s): `body_median_db` must fall back to all speaking frames rather than an empty slice producing NaN. Test added to Task 8.
5. **Stereo 44.1 kHz video container** (`.mp4`/`.mov`): extraction must yield mono 16 kHz and record original channels and sample rate. Test added to Task 2.

---

### Task 1: Backend scaffold, config loading, config hash

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/config.yaml`
- Create: `backend/vocal_coach/__init__.py`
- Create: `backend/vocal_coach/config.py`
- Create: `backend/vocal_coach/analysis/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_config.py`
- Create: `.gitignore`

**Interfaces:**
- Produces: `AnalysisConfig`, `ArticulationConfig`, `AppConfig` (pydantic models), `load_config(path: Path | None = None) -> AppConfig`, `config_hash(cfg: AppConfig) -> str`, `DEFAULT_CONFIG_PATH: Path`.

- [ ] **Step 1: Create project files**

`backend/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "vocal-coach"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "praat-parselmouth>=0.4.3",
  "numpy>=1.26",
  "scipy>=1.11",
  "pydantic>=2.5",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools.packages.find]
include = ["vocal_coach*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`backend/config.yaml`:

```yaml
analysis:
  pitch_floor_hz: 75
  pitch_ceiling_hz: 350
  time_step_s: 0.01
  silence_threshold_db: -25
  min_pause_s: 0.25
  min_sounding_s: 0.10
  creak_threshold_hz: 100
  opening_window_s: 5
  syllable_peak_prominence_db: 2
  intonation_tail_s: 0.08
  intonation_threshold_st: 1.5
  energy_window_s: 15
  phrase_end_tail_s: 0.30
  trailing_off_drop_db: 6
  noise_floor_percentile: 5
  low_confidence_noise_floor_db: 45
  low_confidence_snr_db: 15
  low_confidence_f0_hz: 250
articulation:
  hf_band_hz: [2000, 8000]
  lf_band_hz: [0, 1000]
  modulation_band_hz: [2, 10]
  weak_peak_prominence_db: 4
  formant_max_hz: 5500
  formant_trim_pct: 5
transcription:
  model_size: small
  compute_type: int8
  beam_size: 5
  language: en
  fillers: [um, uh, like, basically, actually, "you know", so]
clarity:
  low_conf_word_prob: 0.5
  word_final_drop_db: 6
  word_final_tail_fraction: 0.3
  min_word_duration_s: 0.25
  rushed_syl_per_sec: 7
  rushed_run_min_words: 3
  low_logprob_segment: -1.0
comparison:
  min_meaningful_change_pct: 5
  directions:
    pitch.f0_range_st: up_good
    pitch.creak_fraction_below_100hz: down_good
    phrasing.long_pause_count_ge_1s: down_good
    phrasing.pauses_per_min: neutral
    intonation.flat_pct: down_good
    energy.trailing_off_count: down_good
    energy.final_vs_body_db: up_good
    articulation.hf_energy_ratio_db: up_good
    articulation.modulation_depth: up_good
    articulation.vowel_space.vowel_space_area_hz2: up_good
    articulation.weak_peak_fraction: down_good
    transcript.derived.fillers_per_min: down_good
    transcript.derived.clarity.low_conf_word_fraction: down_good
    transcript.derived.clarity.word_final_drop_fraction: down_good
    transcript.derived.clarity.rushed_word_fraction: down_good
llm:
  enabled: true
  provider: openai_compatible
  base_url: http://localhost:11434/v1
  model: ""
  allowed_models: []
  seed: 42
  timeout_s: 120
```

`.gitignore` (repo root):

```
.env
data/
backend/.venv/
backend/**/__pycache__/
backend/.pytest_cache/
backend/*.egg-info/
frontend/node_modules/
frontend/dist/
```

Empty files: `backend/vocal_coach/__init__.py`, `backend/vocal_coach/analysis/__init__.py`, `backend/tests/__init__.py`.

- [ ] **Step 2: Create venv and install**

Run from `backend/`:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

Expected: install succeeds, `python -c "import parselmouth"` prints nothing.

- [ ] **Step 3: Write the failing test**

`backend/tests/test_config.py`:

```python
from pathlib import Path

from vocal_coach.config import AppConfig, config_hash, load_config


def test_load_default_config_has_spec_values():
    cfg = load_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.analysis.pitch_floor_hz == 75
    assert cfg.analysis.pitch_ceiling_hz == 350
    assert cfg.analysis.time_step_s == 0.01
    assert cfg.analysis.silence_threshold_db == -25
    assert cfg.analysis.intonation_threshold_st == 1.5
    assert cfg.articulation.hf_band_hz == (2000, 8000)
    assert cfg.articulation.formant_max_hz == 5500


def test_config_hash_is_stable_and_prefixed():
    a = config_hash(load_config())
    b = config_hash(load_config())
    assert a == b
    assert a.startswith("sha256:")
    assert len(a) == len("sha256:") + 64


def test_config_hash_changes_when_analysis_value_changes(tmp_path: Path):
    src = load_config()
    changed = src.model_copy(deep=True)
    changed.analysis.pitch_ceiling_hz = 400
    assert config_hash(src) != config_hash(changed)


def test_config_hash_ignores_non_analysis_sections():
    src = load_config()
    changed = src.model_copy(deep=True)
    changed.raw["llm"]["seed"] = 7
    assert config_hash(src) == config_hash(changed)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.config'`

- [ ] **Step 5: Implement config.py**

`backend/vocal_coach/config.py`:

```python
"""Load config.yaml, validate the analysis sections, compute config_hash."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class AnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pitch_floor_hz: float
    pitch_ceiling_hz: float
    time_step_s: float
    silence_threshold_db: float
    min_pause_s: float
    min_sounding_s: float
    creak_threshold_hz: float
    opening_window_s: float
    syllable_peak_prominence_db: float
    intonation_tail_s: float
    intonation_threshold_st: float
    energy_window_s: float
    phrase_end_tail_s: float
    trailing_off_drop_db: float
    noise_floor_percentile: float
    low_confidence_noise_floor_db: float
    low_confidence_snr_db: float
    low_confidence_f0_hz: float


class ArticulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hf_band_hz: tuple[float, float]
    lf_band_hz: tuple[float, float]
    modulation_band_hz: tuple[float, float]
    weak_peak_prominence_db: float
    formant_max_hz: float
    formant_trim_pct: float


class AppConfig(BaseModel):
    analysis: AnalysisConfig
    articulation: ArticulationConfig
    raw: dict[str, Any]
    """The full YAML document, for sections validated by later plans."""


def load_config(path: Path | None = None) -> AppConfig:
    path = path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return AppConfig(
        analysis=AnalysisConfig(**raw["analysis"]),
        articulation=ArticulationConfig(**raw["articulation"]),
        raw=raw,
    )


def config_hash(cfg: AppConfig) -> str:
    payload = {
        "analysis": cfg.analysis.model_dump(mode="json"),
        "articulation": cfg.articulation.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add .gitignore backend/pyproject.toml backend/config.yaml backend/vocal_coach backend/tests
git commit -m "feat(analysis): scaffold backend package with config loading and config_hash

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Synthetic audio fixtures and ffmpeg extraction

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/synth.py`
- Create: `backend/vocal_coach/analysis/audio.py`
- Create: `backend/tests/test_audio.py`

**Interfaces:**
- Produces (fixtures module `tests/synth.py`): `SR = 16000`; `tone(f0_hz, dur_s, amp=0.3) -> np.ndarray`; `tone_with_tail(f0_hz, dur_s, tail_s, tail_st, amp=0.3) -> np.ndarray`; `silence(dur_s) -> np.ndarray`; `concat(*parts) -> np.ndarray`; `vowel(f1_hz, f2_hz, f0_hz, dur_s, amp=0.3) -> np.ndarray`; `am(x, rate_hz) -> np.ndarray`; `attenuate_tail(x, tail_s, db) -> np.ndarray`; `with_noise_floor(x, level=1e-4) -> np.ndarray`; `to_sound(x) -> parselmouth.Sound`; `write_wav(path, x, sr=SR) -> Path`.
- Produces (`audio.py`): `class AudioInfo(BaseModel): original_channels: int; original_sample_rate: int; duration_s: float; content_sha256: str`; `extract_wav(src: Path, dst: Path) -> AudioInfo`; `check_ffmpeg() -> None` (raises `RuntimeError` if ffmpeg or ffprobe missing); `sha256_file(path: Path) -> str`.

- [ ] **Step 1: Write the synth helpers**

`backend/tests/synth.py`:

```python
"""Deterministic synthetic audio for tests. All at 16 kHz mono float64 in [-1, 1]."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import parselmouth
from scipy.io import wavfile
from scipy.signal import lfilter

SR = 16000


def _t(dur_s: float) -> np.ndarray:
    return np.arange(int(round(dur_s * SR))) / SR


def tone(f0_hz: float, dur_s: float, amp: float = 0.3) -> np.ndarray:
    return amp * np.sin(2 * np.pi * f0_hz * _t(dur_s))


def tone_with_tail(f0_hz: float, dur_s: float, tail_s: float, tail_st: float, amp: float = 0.3) -> np.ndarray:
    """Sine at f0 whose final `tail_s` seconds shift by `tail_st` semitones, phase-continuous."""
    n = int(round(dur_s * SR))
    n_tail = int(round(tail_s * SR))
    freq = np.full(n, f0_hz, dtype=float)
    freq[n - n_tail :] = f0_hz * 2 ** (tail_st / 12)
    phase = np.cumsum(2 * np.pi * freq / SR)
    return amp * np.sin(phase)


def silence(dur_s: float) -> np.ndarray:
    return np.zeros(int(round(dur_s * SR)))


def concat(*parts: np.ndarray) -> np.ndarray:
    return np.concatenate(parts)


def vowel(f1_hz: float, f2_hz: float, f0_hz: float, dur_s: float, amp: float = 0.3) -> np.ndarray:
    """Source-filter vowel: impulse train through two resonators (80 Hz and 90 Hz bandwidth)."""
    n = int(round(dur_s * SR))
    period = int(round(SR / f0_hz))
    src = np.zeros(n)
    src[::period] = 1.0
    y = src
    for f, bw in ((f1_hz, 80.0), (f2_hz, 90.0)):
        r = np.exp(-np.pi * bw / SR)
        theta = 2 * np.pi * f / SR
        a = [1.0, -2 * r * np.cos(theta), r * r]
        y = lfilter([1.0], a, y)
    return amp * y / np.max(np.abs(y))


def am(x: np.ndarray, rate_hz: float) -> np.ndarray:
    """Amplitude-modulate with a raised cosine so troughs reach zero."""
    t = np.arange(len(x)) / SR
    env = 0.5 * (1 - np.cos(2 * np.pi * rate_hz * t))
    return x * env


def attenuate_tail(x: np.ndarray, tail_s: float, db: float) -> np.ndarray:
    y = x.copy()
    n_tail = int(round(tail_s * SR))
    y[len(y) - n_tail :] *= 10 ** (-db / 20)
    return y


def with_noise_floor(x: np.ndarray, level: float = 1e-4) -> np.ndarray:
    """Add seeded low-level noise so digital silence has a finite intensity."""
    rng = np.random.default_rng(0)
    return x + level * rng.standard_normal(len(x))


def to_sound(x: np.ndarray) -> parselmouth.Sound:
    return parselmouth.Sound(x.astype(np.float64), sampling_frequency=SR)


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    pcm = np.clip(x, -1, 1)
    wavfile.write(path, sr, (pcm * 32767).astype(np.int16))
    return path
```

`backend/tests/conftest.py`:

```python
import shutil

import pytest

from vocal_coach.config import AppConfig, load_config


@pytest.fixture(scope="session")
def cfg() -> AppConfig:
    return load_config()


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_audio.py`:

```python
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from tests import synth
from tests.conftest import requires_ffmpeg
from vocal_coach.analysis.audio import AudioInfo, extract_wav, sha256_file


@requires_ffmpeg
def test_extract_stereo_44k_to_mono_16k(tmp_path: Path):
    t = np.arange(int(2.0 * 44100)) / 44100
    left = 0.3 * np.sin(2 * np.pi * 220 * t)
    right = 0.3 * np.sin(2 * np.pi * 330 * t)
    stereo = np.stack([left, right], axis=1)
    src = tmp_path / "in.wav"
    wavfile.write(src, 44100, (stereo * 32767).astype(np.int16))
    dst = tmp_path / "out.wav"

    info = extract_wav(src, dst)

    sr, data = wavfile.read(dst)
    assert sr == 16000
    assert data.ndim == 1
    assert isinstance(info, AudioInfo)
    assert info.original_channels == 2
    assert info.original_sample_rate == 44100
    assert abs(info.duration_s - 2.0) < 0.05
    assert info.content_sha256 == sha256_file(dst)


@requires_ffmpeg
def test_extract_from_mp4_container(tmp_path: Path):
    # Build an mp4 with a silent video track and a stereo audio track using ffmpeg itself.
    import subprocess

    audio = tmp_path / "a.wav"
    synth.write_wav(audio, synth.tone(200, 1.0))  # mono in; ffmpeg upmixes to stereo below
    mp4 = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
         "-i", str(audio), "-ac", "2", "-ar", "44100", "-shortest", str(mp4)],
        check=True,
    )
    dst = tmp_path / "out.wav"

    info = extract_wav(mp4, dst)

    sr, data = wavfile.read(dst)
    assert sr == 16000 and data.ndim == 1
    assert info.original_channels == 2
    assert info.original_sample_rate == 44100


@requires_ffmpeg
def test_extract_is_byte_deterministic(tmp_path: Path):
    src = synth.write_wav(tmp_path / "in.wav", synth.tone(150, 1.0))
    a = extract_wav(src, tmp_path / "a.wav")
    b = extract_wav(src, tmp_path / "b.wav")
    assert a.content_sha256 == b.content_sha256
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_audio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.analysis.audio'`

- [ ] **Step 4: Implement audio.py**

`backend/vocal_coach/analysis/audio.py`:

```python
"""Normalise any audio/video file to mono 16 kHz 16-bit WAV using ffmpeg."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

TARGET_SR = 16000


class AudioInfo(BaseModel):
    original_channels: int
    original_sample_rate: int
    duration_s: float
    content_sha256: str


def check_ffmpeg() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise RuntimeError(f"Required binaries not found on PATH: {', '.join(missing)}. Install ffmpeg.")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=channels,sample_rate", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    streams = json.loads(out).get("streams", [])
    if not streams:
        raise ValueError(f"No audio stream found in {path}")
    s = streams[0]
    return int(s["channels"]), int(s["sample_rate"])


def _duration_s(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def extract_wav(src: Path, dst: Path) -> AudioInfo:
    check_ffmpeg()
    channels, sample_rate = _probe(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1",
         "-ar", str(TARGET_SR), "-sample_fmt", "s16", "-f", "wav", str(dst)],
        check=True,
    )
    return AudioInfo(
        original_channels=channels,
        original_sample_rate=sample_rate,
        duration_s=_duration_s(dst),
        content_sha256=sha256_file(dst),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_audio.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/tests/synth.py backend/tests/conftest.py backend/tests/test_audio.py backend/vocal_coach/analysis/audio.py
git commit -m "feat(analysis): ffmpeg extraction to mono 16 kHz WAV and synthetic test audio

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Shared tracks (F0 + intensity) and semitone helpers

**Files:**
- Create: `backend/vocal_coach/analysis/tracks.py`
- Create: `backend/tests/test_tracks.py`

**Interfaces:**
- Produces: `semitones(a: float | np.ndarray, b: float) -> float | np.ndarray` (= 12·log2(a/b)); `@dataclass class Tracks` with fields `sound: parselmouth.Sound`, `samples: np.ndarray`, `sr: int`, `duration_s: float`, `f0_times: np.ndarray`, `f0_hz: np.ndarray` (NaN where unvoiced), `int_times: np.ndarray`, `intensity_db: np.ndarray`; methods `f0_between(t0, t1) -> np.ndarray` (voiced values only), `intensity_between(t0, t1) -> np.ndarray`, `voiced_mask_at(times: np.ndarray) -> np.ndarray[bool]`; function `extract_tracks(sound: parselmouth.Sound, cfg: AnalysisConfig) -> Tracks`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_tracks.py`:

```python
import numpy as np

from tests import synth
from vocal_coach.analysis.tracks import Tracks, extract_tracks, semitones


def test_semitones_octave_is_twelve():
    assert abs(semitones(200.0, 100.0) - 12.0) < 1e-9
    assert abs(semitones(100.0, 200.0) + 12.0) < 1e-9


def test_extract_tracks_f0_and_intensity(cfg):
    x = synth.with_noise_floor(synth.tone(120, 2.0))
    tr = extract_tracks(synth.to_sound(x), cfg.analysis)
    assert isinstance(tr, Tracks)
    assert tr.sr == synth.SR
    assert abs(tr.duration_s - 2.0) < 0.01
    voiced = tr.f0_hz[~np.isnan(tr.f0_hz)]
    assert len(voiced) > 100
    assert abs(np.median(voiced) - 120) < 2
    assert tr.intensity_db.shape == tr.int_times.shape
    assert np.all(np.isfinite(tr.intensity_db))


def test_f0_between_and_voiced_mask(cfg):
    x = synth.with_noise_floor(synth.concat(synth.tone(120, 1.0), synth.silence(1.0), synth.tone(120, 1.0)))
    tr = extract_tracks(synth.to_sound(x), cfg.analysis)
    assert len(tr.f0_between(0.2, 0.8)) > 40
    assert len(tr.f0_between(1.2, 1.8)) == 0
    mask = tr.voiced_mask_at(np.array([0.5, 1.5, 2.5]))
    assert mask.tolist() == [True, False, True]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tracks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.analysis.tracks'`

- [ ] **Step 3: Implement tracks.py**

`backend/vocal_coach/analysis/tracks.py`:

```python
"""Shared F0 and intensity contours extracted once per recording."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import parselmouth

from vocal_coach.config import AnalysisConfig


def semitones(a, b):
    return 12.0 * np.log2(np.asarray(a, dtype=float) / b)


@dataclass
class Tracks:
    sound: parselmouth.Sound
    samples: np.ndarray
    sr: int
    duration_s: float
    f0_times: np.ndarray
    f0_hz: np.ndarray
    int_times: np.ndarray
    intensity_db: np.ndarray

    def f0_between(self, t0: float, t1: float) -> np.ndarray:
        m = (self.f0_times >= t0) & (self.f0_times <= t1)
        vals = self.f0_hz[m]
        return vals[~np.isnan(vals)]

    def intensity_between(self, t0: float, t1: float) -> np.ndarray:
        m = (self.int_times >= t0) & (self.int_times <= t1)
        return self.intensity_db[m]

    def voiced_mask_at(self, times: np.ndarray) -> np.ndarray:
        idx = np.searchsorted(self.f0_times, times)
        idx = np.clip(idx, 0, len(self.f0_times) - 1)
        return ~np.isnan(self.f0_hz[idx])


def extract_tracks(sound: parselmouth.Sound, cfg: AnalysisConfig) -> Tracks:
    pitch = sound.to_pitch_ac(
        time_step=cfg.time_step_s,
        pitch_floor=cfg.pitch_floor_hz,
        pitch_ceiling=cfg.pitch_ceiling_hz,
    )
    f0 = pitch.selected_array["frequency"].astype(float)
    f0[f0 == 0] = np.nan

    intensity = sound.to_intensity(minimum_pitch=cfg.pitch_floor_hz, time_step=cfg.time_step_s)
    return Tracks(
        sound=sound,
        samples=sound.values[0].astype(float),
        sr=int(round(sound.sampling_frequency)),
        duration_s=float(sound.get_total_duration()),
        f0_times=pitch.xs(),
        f0_hz=f0,
        int_times=intensity.xs(),
        intensity_db=intensity.values[0].astype(float),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tracks.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/analysis/tracks.py backend/tests/test_tracks.py
git commit -m "feat(analysis): shared F0/intensity tracks and semitone helper

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Pitch metrics

**Files:**
- Create: `backend/vocal_coach/analysis/pitch.py`
- Create: `backend/tests/test_pitch.py`

**Interfaces:**
- Consumes: `Tracks`, `semitones`, `AnalysisConfig`.
- Produces: `class PitchBlock(BaseModel)` with `f0_median_hz: float | None`, `f0_p10_hz: float | None`, `f0_p90_hz: float | None`, `f0_range_st: float | None`, `voiced_fraction: float`, `creak_fraction_below_100hz: float | None`, `opening_f0_median_hz: float | None`, `opening_vs_overall_st: float | None`; `compute(tracks: Tracks, cfg: AnalysisConfig) -> PitchBlock`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pitch.py`:

```python
import numpy as np

from tests import synth
from vocal_coach.analysis import pitch
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def test_steady_tone_median(cfg):
    blk = pitch.compute(_tracks(synth.tone(120, 3.0), cfg), cfg.analysis)
    assert abs(blk.f0_median_hz - 120) < 2
    assert blk.voiced_fraction > 0.9
    assert blk.f0_range_st < 1.0


def test_two_tones_octave_apart_range(cfg):
    x = synth.concat(synth.tone(100, 2.0), synth.tone(200, 2.0))
    blk = pitch.compute(_tracks(x, cfg), cfg.analysis)
    assert abs(blk.f0_range_st - 12) < 1.0


def test_creak_fraction(cfg):
    x = synth.concat(synth.tone(85, 2.0), synth.tone(150, 2.0))
    blk = pitch.compute(_tracks(x, cfg), cfg.analysis)
    assert 0.4 < blk.creak_fraction_below_100hz < 0.6


def test_opening_vs_overall(cfg):
    x = synth.concat(synth.tone(200, 5.0), synth.tone(100, 10.0))
    blk = pitch.compute(_tracks(x, cfg), cfg.analysis)
    assert abs(blk.opening_f0_median_hz - 200) < 3
    assert blk.opening_vs_overall_st > 10


def test_long_leading_silence_gives_null_opening(cfg):
    x = synth.concat(synth.silence(6.0), synth.tone(120, 3.0))
    blk = pitch.compute(_tracks(x, cfg), cfg.analysis)
    assert blk.opening_f0_median_hz is None
    assert blk.opening_vs_overall_st is None
    assert abs(blk.f0_median_hz - 120) < 2


def test_no_voiced_frames_gives_nulls(cfg):
    blk = pitch.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis)
    assert blk.f0_median_hz is None
    assert blk.f0_range_st is None
    assert blk.creak_fraction_below_100hz is None
    assert blk.voiced_fraction == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pitch.py -v`
Expected: FAIL with `ImportError: cannot import name 'pitch'`

- [ ] **Step 3: Implement pitch.py**

`backend/vocal_coach/analysis/pitch.py`:

```python
"""Pitch metrics: median F0, robust range, creak share, opening vs overall."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vocal_coach.analysis.tracks import Tracks, semitones
from vocal_coach.config import AnalysisConfig


class PitchBlock(BaseModel):
    f0_median_hz: float | None
    f0_p10_hz: float | None
    f0_p90_hz: float | None
    f0_range_st: float | None
    voiced_fraction: float
    creak_fraction_below_100hz: float | None
    opening_f0_median_hz: float | None
    opening_vs_overall_st: float | None


def compute(tracks: Tracks, cfg: AnalysisConfig) -> PitchBlock:
    f0 = tracks.f0_hz
    voiced = f0[~np.isnan(f0)]
    n_frames = len(f0)
    voiced_fraction = float(len(voiced) / n_frames) if n_frames else 0.0

    if len(voiced) == 0:
        return PitchBlock(
            f0_median_hz=None, f0_p10_hz=None, f0_p90_hz=None, f0_range_st=None,
            voiced_fraction=voiced_fraction, creak_fraction_below_100hz=None,
            opening_f0_median_hz=None, opening_vs_overall_st=None,
        )

    median = float(np.median(voiced))
    p10 = float(np.percentile(voiced, 10))
    p90 = float(np.percentile(voiced, 90))
    creak = float(np.mean(voiced < cfg.creak_threshold_hz))

    opening = tracks.f0_between(0.0, cfg.opening_window_s)
    if len(opening) == 0:
        opening_median = None
        opening_vs_overall = None
    else:
        opening_median = float(np.median(opening))
        opening_vs_overall = float(semitones(opening_median, median))

    return PitchBlock(
        f0_median_hz=median,
        f0_p10_hz=p10,
        f0_p90_hz=p90,
        f0_range_st=float(semitones(p90, p10)),
        voiced_fraction=voiced_fraction,
        creak_fraction_below_100hz=creak,
        opening_f0_median_hz=opening_median,
        opening_vs_overall_st=opening_vs_overall,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pitch.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/analysis/pitch.py backend/tests/test_pitch.py
git commit -m "feat(analysis): pitch metrics

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Phrasing (phrases and pauses)

**Files:**
- Create: `backend/vocal_coach/analysis/phrasing.py`
- Create: `backend/tests/test_phrasing.py`

**Interfaces:**
- Consumes: `Tracks`, `AnalysisConfig`.
- Produces: `class Interval(BaseModel): start_s: float; end_s: float; duration_s: float`; `class PhrasingBlock(BaseModel)` with `phrase_count: int`, `speaking_time_s: float`, `mean_phrase_length_s: float | None`, `pause_count: int`, `pauses_per_min: float`, `mean_pause_length_s: float | None`, `long_pause_count_ge_1s: int`, `long_pauses: list[Interval]`; `class PhrasingResult(NamedTuple): block: PhrasingBlock; phrases: list[Interval]; pauses: list[Interval]`; `compute(tracks: Tracks, cfg: AnalysisConfig) -> PhrasingResult`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_phrasing.py`:

```python
from tests import synth
from vocal_coach.analysis import phrasing
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def test_three_phrases_two_pauses_one_long(cfg):
    x = synth.concat(
        synth.tone(120, 2.0), synth.silence(0.5),
        synth.tone(120, 2.0), synth.silence(1.5),
        synth.tone(120, 2.0),
    )
    res = phrasing.compute(_tracks(x, cfg), cfg.analysis)
    blk = res.block
    assert blk.phrase_count == 3
    assert blk.pause_count == 2
    assert blk.long_pause_count_ge_1s == 1
    assert len(res.phrases) == 3
    assert len(res.pauses) == 2
    assert abs(blk.speaking_time_s - 6.0) < 0.3
    assert abs(blk.mean_phrase_length_s - 2.0) < 0.15
    assert abs(blk.mean_pause_length_s - 1.0) < 0.15
    assert abs(res.pauses[1].duration_s - 1.5) < 0.15
    assert len(blk.long_pauses) == 1 and abs(blk.long_pauses[0].start_s - 4.5) < 0.15


def test_leading_and_trailing_silence_not_pauses(cfg):
    x = synth.concat(synth.silence(1.0), synth.tone(120, 2.0), synth.silence(1.0))
    res = phrasing.compute(_tracks(x, cfg), cfg.analysis)
    assert res.block.phrase_count == 1
    assert res.block.pause_count == 0
    assert res.block.pauses_per_min == 0.0


def test_gap_shorter_than_min_pause_is_ignored(cfg):
    x = synth.concat(synth.tone(120, 2.0), synth.silence(0.1), synth.tone(120, 2.0))
    res = phrasing.compute(_tracks(x, cfg), cfg.analysis)
    assert res.block.phrase_count == 1


def test_all_silence(cfg):
    res = phrasing.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis)
    assert res.block.phrase_count == 0
    assert res.block.mean_phrase_length_s is None
    assert res.block.speaking_time_s == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_phrasing.py -v`
Expected: FAIL with `ImportError: cannot import name 'phrasing'`

- [ ] **Step 3: Implement phrasing.py**

`backend/vocal_coach/analysis/phrasing.py`:

```python
"""Phrases and pauses from Praat 'To TextGrid (silences)'."""
from __future__ import annotations

from typing import NamedTuple

from parselmouth.praat import call
from pydantic import BaseModel

from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig

LONG_PAUSE_S = 1.0  # the metric name 'long_pause_count_ge_1s' fixes this; not configurable


class Interval(BaseModel):
    start_s: float
    end_s: float
    duration_s: float


class PhrasingBlock(BaseModel):
    phrase_count: int
    speaking_time_s: float
    mean_phrase_length_s: float | None
    pause_count: int
    pauses_per_min: float
    mean_pause_length_s: float | None
    long_pause_count_ge_1s: int
    long_pauses: list[Interval]


class PhrasingResult(NamedTuple):
    block: PhrasingBlock
    phrases: list[Interval]
    pauses: list[Interval]


def _interval(t0: float, t1: float) -> Interval:
    return Interval(start_s=float(t0), end_s=float(t1), duration_s=float(t1 - t0))


def _sounding_intervals(tracks: Tracks, cfg: AnalysisConfig) -> list[Interval]:
    tg = call(
        tracks.sound, "To TextGrid (silences)",
        cfg.pitch_floor_hz, cfg.time_step_s, cfg.silence_threshold_db,
        cfg.min_pause_s, cfg.min_sounding_s, "silent", "sounding",
    )
    n = int(call(tg, "Get number of intervals", 1))
    out: list[Interval] = []
    for i in range(1, n + 1):
        if call(tg, "Get label of interval", 1, i) == "sounding":
            t0 = call(tg, "Get start time of interval", 1, i)
            t1 = call(tg, "Get end time of interval", 1, i)
            out.append(_interval(t0, t1))
    return out


def compute(tracks: Tracks, cfg: AnalysisConfig) -> PhrasingResult:
    phrases = _sounding_intervals(tracks, cfg)
    pauses = [_interval(a.end_s, b.start_s) for a, b in zip(phrases, phrases[1:])]
    long_pauses = [p for p in pauses if p.duration_s >= LONG_PAUSE_S]
    speaking_time = sum(p.duration_s for p in phrases)
    minutes = tracks.duration_s / 60.0

    block = PhrasingBlock(
        phrase_count=len(phrases),
        speaking_time_s=float(speaking_time),
        mean_phrase_length_s=float(speaking_time / len(phrases)) if phrases else None,
        pause_count=len(pauses),
        pauses_per_min=float(len(pauses) / minutes) if minutes > 0 else 0.0,
        mean_pause_length_s=float(sum(p.duration_s for p in pauses) / len(pauses)) if pauses else None,
        long_pause_count_ge_1s=len(long_pauses),
        long_pauses=long_pauses,
    )
    return PhrasingResult(block=block, phrases=phrases, pauses=pauses)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_phrasing.py -v`
Expected: 4 passed. If `test_three_phrases_two_pauses_one_long` fails on `speaking_time_s`, Praat's silence detector trims phrase edges by up to one analysis window; the tolerances above already allow 0.3 s, so widen only if the measured value is reported and the phrase/pause counts are right.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/analysis/phrasing.py backend/tests/test_phrasing.py
git commit -m "feat(analysis): phrase and pause detection

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Pace (syllable nuclei)

**Files:**
- Create: `backend/vocal_coach/analysis/pace.py`
- Create: `backend/tests/test_pace.py`

**Interfaces:**
- Consumes: `Tracks`, `AnalysisConfig`, `speaking_time_s: float` from `PhrasingBlock`.
- Produces: `class PaceBlock(BaseModel): syllable_count_est: int; syllables_per_sec_overall: float; articulation_rate_syl_per_sec: float | None`; `class PaceResult(NamedTuple): block: PaceBlock; peak_times: np.ndarray; peak_prominences_db: np.ndarray`; `compute(tracks: Tracks, cfg: AnalysisConfig, speaking_time_s: float) -> PaceResult`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pace.py`:

```python
from tests import synth
from vocal_coach.analysis import pace
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def test_four_hz_am_gives_about_twenty_syllables(cfg):
    x = synth.am(synth.vowel(500, 1500, 120, 5.0), rate_hz=4.0)
    res = pace.compute(_tracks(x, cfg), cfg.analysis, speaking_time_s=5.0)
    assert 18 <= res.block.syllable_count_est <= 22
    assert 3.6 <= res.block.syllables_per_sec_overall <= 4.4
    assert abs(res.block.articulation_rate_syl_per_sec - res.block.syllables_per_sec_overall) < 1e-9
    assert len(res.peak_times) == res.block.syllable_count_est
    assert len(res.peak_prominences_db) == res.block.syllable_count_est
    assert res.peak_prominences_db.min() >= cfg.analysis.syllable_peak_prominence_db


def test_articulation_rate_uses_speaking_time(cfg):
    x = synth.concat(synth.am(synth.vowel(500, 1500, 120, 5.0), 4.0), synth.silence(5.0))
    res = pace.compute(_tracks(x, cfg), cfg.analysis, speaking_time_s=5.0)
    assert 1.8 <= res.block.syllables_per_sec_overall <= 2.2
    assert 3.6 <= res.block.articulation_rate_syl_per_sec <= 4.4


def test_silence_gives_zero(cfg):
    res = pace.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis, speaking_time_s=0.0)
    assert res.block.syllable_count_est == 0
    assert res.block.syllables_per_sec_overall == 0.0
    assert res.block.articulation_rate_syl_per_sec is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pace.py -v`
Expected: FAIL with `ImportError: cannot import name 'pace'`

- [ ] **Step 3: Implement pace.py**

`backend/vocal_coach/analysis/pace.py`:

```python
"""Syllable-rate estimate from voiced intensity peaks."""
from __future__ import annotations

from typing import NamedTuple

import numpy as np
from pydantic import BaseModel
from scipy.signal import find_peaks

from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig


class PaceBlock(BaseModel):
    syllable_count_est: int
    syllables_per_sec_overall: float
    articulation_rate_syl_per_sec: float | None


class PaceResult(NamedTuple):
    block: PaceBlock
    peak_times: np.ndarray
    peak_prominences_db: np.ndarray


def compute(tracks: Tracks, cfg: AnalysisConfig, speaking_time_s: float) -> PaceResult:
    intensity = tracks.intensity_db.copy()
    voiced = tracks.voiced_mask_at(tracks.int_times)
    # Push unvoiced frames far below everything so peaks can only form in voiced regions.
    floor = float(np.nanmin(intensity)) - 100.0 if len(intensity) else 0.0
    intensity[~voiced] = floor

    all_peaks, all_props = find_peaks(intensity, prominence=cfg.syllable_peak_prominence_db)
    keep = voiced[all_peaks]
    peak_idx = all_peaks[keep]
    prominences = all_props["prominences"][keep]

    count = int(len(peak_idx))
    overall = float(count / tracks.duration_s) if tracks.duration_s > 0 else 0.0
    articulation = float(count / speaking_time_s) if speaking_time_s > 0 else None

    return PaceResult(
        block=PaceBlock(
            syllable_count_est=count,
            syllables_per_sec_overall=overall,
            articulation_rate_syl_per_sec=articulation,
        ),
        peak_times=tracks.int_times[peak_idx],
        peak_prominences_db=prominences.astype(float),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pace.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/analysis/pace.py backend/tests/test_pace.py
git commit -m "feat(analysis): syllable rate from intensity peaks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Intonation (phrase-final contour)

**Files:**
- Create: `backend/vocal_coach/analysis/intonation.py`
- Create: `backend/tests/test_intonation.py`

**Interfaces:**
- Consumes: `Tracks`, `AnalysisConfig`, `phrases: list[Interval]`.
- Produces: `class PhraseContour(BaseModel): start_s: float; end_s: float; end_delta_st: float; class_: Literal["up","down","flat"]` serialised with alias `class`; `class IntonationBlock(BaseModel)` with `up_count`, `down_count`, `flat_count`, `unclassified_count` (ints), `flat_pct: float | None`, `per_phrase: list[PhraseContour]`; `compute(tracks: Tracks, cfg: AnalysisConfig, phrases: list[Interval]) -> IntonationBlock`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_intonation.py`:

```python
from tests import synth
from vocal_coach.analysis import intonation
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def _phrase(t0, t1):
    return Interval(start_s=t0, end_s=t1, duration_s=t1 - t0)


def test_rising_falling_flat(cfg):
    up = synth.tone_with_tail(120, 2.0, tail_s=0.3, tail_st=+3)
    down = synth.tone_with_tail(120, 2.0, tail_s=0.3, tail_st=-3)
    flat = synth.tone(120, 2.0)
    x = synth.concat(up, synth.silence(0.5), down, synth.silence(0.5), flat)
    phrases = [_phrase(0.0, 2.0), _phrase(2.5, 4.5), _phrase(5.0, 7.0)]
    blk = intonation.compute(_tracks(x, cfg), cfg.analysis, phrases)
    assert [p.class_ for p in blk.per_phrase] == ["up", "down", "flat"]
    assert blk.up_count == 1 and blk.down_count == 1 and blk.flat_count == 1
    assert blk.unclassified_count == 0
    assert abs(blk.flat_pct - 33.3333) < 0.01
    assert blk.per_phrase[0].end_delta_st > 1.5
    assert blk.per_phrase[1].end_delta_st < -1.5


def test_phrase_with_unvoiced_tail_is_unclassified(cfg):
    # 1 s tone then 0.3 s of silence inside the declared phrase -> no voiced frames in last 80 ms.
    x = synth.concat(synth.tone(120, 1.0), synth.silence(0.3))
    blk = intonation.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 1.3)])
    assert blk.unclassified_count == 1
    assert blk.per_phrase == []
    assert blk.flat_pct is None


def test_per_phrase_serialises_class_key(cfg):
    x = synth.tone(120, 2.0)
    blk = intonation.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 2.0)])
    dumped = blk.model_dump(by_alias=True)
    assert dumped["per_phrase"][0]["class"] == "flat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_intonation.py -v`
Expected: FAIL with `ImportError: cannot import name 'intonation'`

- [ ] **Step 3: Implement intonation.py**

`backend/vocal_coach/analysis/intonation.py`:

```python
"""Phrase-final pitch movement: up / down / flat."""
from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import Tracks, semitones
from vocal_coach.config import AnalysisConfig


class PhraseContour(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_s: float
    end_s: float
    end_delta_st: float
    class_: Literal["up", "down", "flat"] = Field(alias="class")


class IntonationBlock(BaseModel):
    up_count: int
    down_count: int
    flat_count: int
    unclassified_count: int
    flat_pct: float | None
    per_phrase: list[PhraseContour]


def compute(tracks: Tracks, cfg: AnalysisConfig, phrases: list[Interval]) -> IntonationBlock:
    per_phrase: list[PhraseContour] = []
    unclassified = 0
    for ph in phrases:
        whole = tracks.f0_between(ph.start_s, ph.end_s)
        tail = tracks.f0_between(ph.end_s - cfg.intonation_tail_s, ph.end_s)
        if len(whole) == 0 or len(tail) == 0:
            unclassified += 1
            continue
        delta = float(semitones(np.median(tail), float(np.median(whole))))
        if delta > cfg.intonation_threshold_st:
            cls = "up"
        elif delta < -cfg.intonation_threshold_st:
            cls = "down"
        else:
            cls = "flat"
        per_phrase.append(PhraseContour(start_s=ph.start_s, end_s=ph.end_s, end_delta_st=delta, class_=cls))

    up = sum(p.class_ == "up" for p in per_phrase)
    down = sum(p.class_ == "down" for p in per_phrase)
    flat = sum(p.class_ == "flat" for p in per_phrase)
    classified = up + down + flat
    return IntonationBlock(
        up_count=up,
        down_count=down,
        flat_count=flat,
        unclassified_count=unclassified,
        flat_pct=float(100.0 * flat / classified) if classified else None,
        per_phrase=per_phrase,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_intonation.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/analysis/intonation.py backend/tests/test_intonation.py
git commit -m "feat(analysis): phrase-final intonation classification

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Energy (final window, trailing off)

**Files:**
- Create: `backend/vocal_coach/analysis/energy.py`
- Create: `backend/tests/test_energy.py`

**Interfaces:**
- Consumes: `Tracks`, `AnalysisConfig`, `phrases: list[Interval]`.
- Produces: `class EnergyBlock(BaseModel)` with `body_median_db: float | None`, `final_15s_median_db: float | None`, `final_vs_body_db: float | None`, `trailing_off_count: int`, `per_phrase_end_drop_db: list[float]`; `compute(tracks: Tracks, cfg: AnalysisConfig, phrases: list[Interval]) -> EnergyBlock`; helper `speaking_mask(tracks: Tracks, phrases: list[Interval]) -> np.ndarray[bool]` over `tracks.int_times` (reused by Task 10).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_energy.py`:

```python
from tests import synth
from vocal_coach.analysis import energy
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def _phrase(t0, t1):
    return Interval(start_s=t0, end_s=t1, duration_s=t1 - t0)


def test_trailing_off_detected(cfg):
    quiet_end = synth.attenuate_tail(synth.tone(120, 2.0), tail_s=0.3, db=10)
    steady = synth.tone(120, 2.0)
    x = synth.concat(quiet_end, synth.silence(0.5), steady)
    blk = energy.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 2.0), _phrase(2.5, 4.5)])
    assert blk.trailing_off_count == 1
    assert len(blk.per_phrase_end_drop_db) == 2
    assert blk.per_phrase_end_drop_db[0] < -6
    assert abs(blk.per_phrase_end_drop_db[1]) < 2


def test_final_window_vs_body(cfg):
    # 40 s: first 25 s at full level, last 15 s attenuated 6 dB.
    loud = synth.tone(120, 25.0)
    soft = synth.tone(120, 15.0) * 10 ** (-6 / 20)
    x = synth.concat(loud, soft)
    blk = energy.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 40.0)])
    assert -7.5 < blk.final_vs_body_db < -4.5


def test_short_recording_body_falls_back_to_all_speech(cfg):
    x = synth.tone(120, 10.0)
    blk = energy.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 10.0)])
    assert blk.body_median_db is not None
    assert blk.final_15s_median_db is not None
    assert abs(blk.final_vs_body_db) < 1.0


def test_no_phrases(cfg):
    blk = energy.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis, [])
    assert blk.body_median_db is None
    assert blk.final_vs_body_db is None
    assert blk.trailing_off_count == 0
    assert blk.per_phrase_end_drop_db == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_energy.py -v`
Expected: FAIL with `ImportError: cannot import name 'energy'`

- [ ] **Step 3: Implement energy.py**

`backend/vocal_coach/analysis/energy.py`:

```python
"""Energy: body vs final window, per-phrase trailing off."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig


class EnergyBlock(BaseModel):
    body_median_db: float | None
    final_15s_median_db: float | None
    final_vs_body_db: float | None
    trailing_off_count: int
    per_phrase_end_drop_db: list[float]


def speaking_mask(tracks: Tracks, phrases: list[Interval]) -> np.ndarray:
    mask = np.zeros(len(tracks.int_times), dtype=bool)
    for ph in phrases:
        mask |= (tracks.int_times >= ph.start_s) & (tracks.int_times <= ph.end_s)
    return mask


def _median_or_none(values: np.ndarray) -> float | None:
    return float(np.median(values)) if len(values) else None


def compute(tracks: Tracks, cfg: AnalysisConfig, phrases: list[Interval]) -> EnergyBlock:
    speaking = speaking_mask(tracks, phrases)
    times = tracks.int_times
    inten = tracks.intensity_db

    final_start = tracks.duration_s - cfg.energy_window_s
    final_mask = speaking & (times >= final_start)
    body_mask = speaking & (times < final_start)
    if not body_mask.any():
        body_mask = speaking  # recording shorter than two windows: body = all speech

    body = _median_or_none(inten[body_mask])
    final = _median_or_none(inten[final_mask])
    final_vs_body = float(final - body) if body is not None and final is not None else None

    drops: list[float] = []
    for ph in phrases:
        whole = tracks.intensity_between(ph.start_s, ph.end_s)
        tail = tracks.intensity_between(ph.end_s - cfg.phrase_end_tail_s, ph.end_s)
        if len(whole) == 0 or len(tail) == 0:
            continue
        drops.append(float(np.median(tail) - np.median(whole)))

    trailing = sum(d < -cfg.trailing_off_drop_db for d in drops)
    return EnergyBlock(
        body_median_db=body,
        final_15s_median_db=final,
        final_vs_body_db=final_vs_body,
        trailing_off_count=int(trailing),
        per_phrase_end_drop_db=drops,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_energy.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/analysis/energy.py backend/tests/test_energy.py
git commit -m "feat(analysis): energy and trailing-off metrics

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Recording quality and voice quality

**Files:**
- Create: `backend/vocal_coach/analysis/quality.py`
- Create: `backend/vocal_coach/analysis/voice_quality.py`
- Create: `backend/tests/test_quality.py`

**Interfaces:**
- Consumes: `Tracks`, `AnalysisConfig`, `phrases`, `speaking_mask`.
- Produces (`quality.py`): `class RecordingQualityBlock(BaseModel): noise_floor_db: float; snr_estimate_db: float | None; low_confidence: bool; reasons: list[str]`; `compute(tracks, cfg, phrases) -> RecordingQualityBlock`. Reasons used: `"high_noise_floor"`, `"low_snr"`, `"no_voiced_speech"`.
- Produces (`voice_quality.py`): `class VoiceQualityBlock(BaseModel): hnr_db: float | None; jitter_local: float | None; shimmer_local: float | None; low_confidence: bool`; `compute(tracks, cfg, low_confidence: bool) -> VoiceQualityBlock`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_quality.py`:

```python
from tests import synth
from vocal_coach.analysis import quality, voice_quality
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg, noise=1e-4):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x, level=noise)), cfg.analysis)


def _phrase(t0, t1):
    return Interval(start_s=t0, end_s=t1, duration_s=t1 - t0)


def test_clean_recording_not_low_confidence(cfg):
    x = synth.concat(synth.tone(120, 3.0), synth.silence(1.0))
    blk = quality.compute(_tracks(x, cfg), cfg.analysis, [_phrase(0.0, 3.0)])
    assert blk.low_confidence is False
    assert blk.reasons == []
    assert blk.snr_estimate_db > 15


def test_noisy_recording_flags_low_snr(cfg):
    x = synth.concat(synth.tone(120, 3.0, amp=0.05), synth.silence(1.0))
    blk = quality.compute(_tracks(x, cfg, noise=0.02), cfg.analysis, [_phrase(0.0, 3.0)])
    assert blk.low_confidence is True
    assert "low_snr" in blk.reasons


def test_silence_flags_no_voiced_speech(cfg):
    blk = quality.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis, [])
    assert "no_voiced_speech" in blk.reasons
    assert blk.snr_estimate_db is None


def test_voice_quality_values_on_pure_tone(cfg):
    blk = voice_quality.compute(_tracks(synth.tone(120, 3.0), cfg), cfg.analysis, low_confidence=False)
    assert blk.hnr_db > 20
    assert 0 <= blk.jitter_local < 0.01
    assert 0 <= blk.shimmer_local < 0.05
    assert blk.low_confidence is False


def test_voice_quality_on_silence_is_null(cfg):
    blk = voice_quality.compute(_tracks(synth.silence(3.0), cfg), cfg.analysis, low_confidence=True)
    assert blk.hnr_db is None and blk.jitter_local is None and blk.shimmer_local is None
    assert blk.low_confidence is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quality.py -v`
Expected: FAIL with `ImportError: cannot import name 'quality'`

- [ ] **Step 3: Implement quality.py**

`backend/vocal_coach/analysis/quality.py`:

```python
"""Recording quality: noise floor, SNR estimate, low-confidence flag."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vocal_coach.analysis.energy import speaking_mask
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig


class RecordingQualityBlock(BaseModel):
    noise_floor_db: float
    snr_estimate_db: float | None
    low_confidence: bool
    reasons: list[str]


def compute(tracks: Tracks, cfg: AnalysisConfig, phrases: list[Interval]) -> RecordingQualityBlock:
    inten = tracks.intensity_db
    noise_floor = float(np.percentile(inten, cfg.noise_floor_percentile)) if len(inten) else 0.0
    speaking = speaking_mask(tracks, phrases)
    has_voiced = bool(np.any(~np.isnan(tracks.f0_hz)))

    reasons: list[str] = []
    snr: float | None = None
    if speaking.any() and has_voiced:
        snr = float(np.median(inten[speaking]) - noise_floor)
        if snr < cfg.low_confidence_snr_db:
            reasons.append("low_snr")
    else:
        reasons.append("no_voiced_speech")
    if noise_floor > cfg.low_confidence_noise_floor_db:
        reasons.append("high_noise_floor")

    return RecordingQualityBlock(
        noise_floor_db=noise_floor,
        snr_estimate_db=snr,
        low_confidence=bool(reasons),
        reasons=reasons,
    )
```

- [ ] **Step 4: Implement voice_quality.py**

`backend/vocal_coach/analysis/voice_quality.py`:

```python
"""HNR, jitter, shimmer via Praat."""
from __future__ import annotations

import math

import numpy as np
from parselmouth.praat import call
from pydantic import BaseModel

from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import AnalysisConfig


class VoiceQualityBlock(BaseModel):
    hnr_db: float | None
    jitter_local: float | None
    shimmer_local: float | None
    low_confidence: bool


def _finite(v: float) -> float | None:
    return float(v) if v is not None and math.isfinite(v) else None


def compute(tracks: Tracks, cfg: AnalysisConfig, low_confidence: bool) -> VoiceQualityBlock:
    if not np.any(~np.isnan(tracks.f0_hz)):
        return VoiceQualityBlock(hnr_db=None, jitter_local=None, shimmer_local=None, low_confidence=low_confidence)

    harmonicity = tracks.sound.to_harmonicity_cc(
        time_step=cfg.time_step_s, minimum_pitch=cfg.pitch_floor_hz, silence_threshold=0.1, periods_per_window=1.0
    )
    hnr = call(harmonicity, "Get mean", 0, 0)

    point_process = call(tracks.sound, "To PointProcess (periodic, cc)", cfg.pitch_floor_hz, cfg.pitch_ceiling_hz)
    jitter = call(point_process, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
    shimmer = call([tracks.sound, point_process], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6)

    return VoiceQualityBlock(
        hnr_db=_finite(hnr),
        jitter_local=_finite(jitter),
        shimmer_local=_finite(shimmer),
        low_confidence=low_confidence,
    )
```

The `silence_threshold=0.1` and `periods_per_window=1.0` are Praat's documented defaults for `To Harmonicity (cc)`, and the `0.0001, 0.02, 1.3, 1.6` arguments are Praat's documented defaults for jitter/shimmer period windows; they are algorithm constants, not coaching thresholds, so they stay as literals with this comment above them in the file.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_quality.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/vocal_coach/analysis/quality.py backend/vocal_coach/analysis/voice_quality.py backend/tests/test_quality.py
git commit -m "feat(analysis): recording quality flags and HNR/jitter/shimmer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Articulation proxies

**Files:**
- Create: `backend/vocal_coach/analysis/articulation.py`
- Create: `backend/tests/test_articulation.py`

**Interfaces:**
- Consumes: `Tracks`, `AnalysisConfig`, `ArticulationConfig`, `phrases`, `peak_prominences_db` from `PaceResult`, `speaking_mask`, `f0_median_hz`, `recording_low_confidence`.
- Produces: `class VowelSpace(BaseModel): f1_sd_hz: float | None; f2_sd_hz: float | None; vowel_space_area_hz2: float | None; vowel_dispersion_st: float | None`; `class ArticulationBlock(BaseModel)` with `hf_energy_ratio_db: float | None`, `spectral_tilt_db_per_oct: float | None`, `modulation_depth: float | None`, `syllable_peak_prominence_mean_db: float | None`, `syllable_peak_prominence_p25_db: float | None`, `weak_peak_fraction: float | None`, `vowel_space: VowelSpace`, `low_confidence: bool`; `compute(tracks, acfg: AnalysisConfig, art: ArticulationConfig, phrases, peak_prominences_db: np.ndarray, f0_median_hz: float | None, recording_low_confidence: bool) -> ArticulationBlock`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_articulation.py`:

```python
import numpy as np
from scipy.signal import butter, sosfiltfilt

from tests import synth
from vocal_coach.analysis import articulation
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def _phrase(t0, t1):
    return Interval(start_s=t0, end_s=t1, duration_s=t1 - t0)


def _run(x, cfg, proms=None, f0=120.0, low_conf=False):
    tr = _tracks(x, cfg)
    proms = np.array([6.0, 8.0, 7.0]) if proms is None else np.asarray(proms, dtype=float)
    return articulation.compute(tr, cfg.analysis, cfg.articulation, [_phrase(0.0, tr.duration_s)], proms, f0, low_conf)


def test_lowpass_reduces_hf_ratio_and_steepens_tilt(cfg):
    clear = synth.vowel(500, 1500, 120, 3.0)
    sos = butter(4, 1500, btype="low", fs=synth.SR, output="sos")
    muffled = sosfiltfilt(sos, clear)
    a = _run(clear, cfg)
    b = _run(muffled, cfg)
    assert b.hf_energy_ratio_db < a.hf_energy_ratio_db - 10
    assert b.spectral_tilt_db_per_oct < a.spectral_tilt_db_per_oct


def test_flattened_envelope_reduces_modulation_depth(cfg):
    modulated = synth.am(synth.vowel(500, 1500, 120, 4.0), 4.0)
    flat = synth.vowel(500, 1500, 120, 4.0)
    assert _run(flat, cfg).modulation_depth < _run(modulated, cfg).modulation_depth


def test_peak_prominence_stats(cfg):
    blk = _run(synth.vowel(500, 1500, 120, 2.0), cfg, proms=[2.0, 3.0, 5.0, 9.0])
    assert abs(blk.syllable_peak_prominence_mean_db - 4.75) < 1e-9
    assert abs(blk.syllable_peak_prominence_p25_db - 2.75) < 1e-9
    assert abs(blk.weak_peak_fraction - 0.5) < 1e-9


def test_two_vowels_have_larger_space_than_one(cfg):
    two = synth.concat(synth.vowel(300, 2300, 120, 2.0), synth.vowel(750, 1200, 120, 2.0))
    one = synth.vowel(500, 1500, 120, 4.0)
    a = _run(two, cfg).vowel_space
    b = _run(one, cfg).vowel_space
    assert a.vowel_space_area_hz2 > 5 * b.vowel_space_area_hz2
    assert a.f2_sd_hz > b.f2_sd_hz
    assert a.vowel_dispersion_st > b.vowel_dispersion_st


def test_low_confidence_from_recording_or_high_pitch(cfg):
    x = synth.vowel(500, 1500, 120, 2.0)
    assert _run(x, cfg, low_conf=True).low_confidence is True
    assert _run(x, cfg, f0=300.0).low_confidence is True
    assert _run(x, cfg).low_confidence is False


def test_silence_gives_nulls(cfg):
    tr = _tracks(synth.silence(2.0), cfg)
    blk = articulation.compute(tr, cfg.analysis, cfg.articulation, [], np.array([]), None, True)
    assert blk.hf_energy_ratio_db is None
    assert blk.modulation_depth is None
    assert blk.weak_peak_fraction is None
    assert blk.vowel_space.vowel_space_area_hz2 is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_articulation.py -v`
Expected: FAIL with `ImportError: cannot import name 'articulation'`

- [ ] **Step 3: Implement articulation.py**

`backend/vocal_coach/analysis/articulation.py`:

```python
"""Articulation proxies: spectral balance, envelope modulation, syllable peak strength, vowel space."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel
from scipy.signal import butter, sosfiltfilt, stft, welch
from scipy.spatial import ConvexHull, QhullError

from vocal_coach.analysis.energy import speaking_mask
from vocal_coach.analysis.phrasing import Interval
from vocal_coach.analysis.tracks import Tracks, semitones
from vocal_coach.config import AnalysisConfig, ArticulationConfig

# STFT framing: 25 ms Hann window, 10 ms hop (algorithm constants, not coaching thresholds).
STFT_WINDOW_S = 0.025
STFT_HOP_S = 0.010
TILT_BAND_HZ = (500.0, 8000.0)
WELCH_NPERSEG = 1024
FORMANT_TIME_STEP_S = 0.01
FORMANT_COUNT = 5
FORMANT_WINDOW_S = 0.025
FORMANT_PREEMPHASIS_HZ = 50.0


class VowelSpace(BaseModel):
    f1_sd_hz: float | None
    f2_sd_hz: float | None
    vowel_space_area_hz2: float | None
    vowel_dispersion_st: float | None


class ArticulationBlock(BaseModel):
    hf_energy_ratio_db: float | None
    spectral_tilt_db_per_oct: float | None
    modulation_depth: float | None
    syllable_peak_prominence_mean_db: float | None
    syllable_peak_prominence_p25_db: float | None
    weak_peak_fraction: float | None
    vowel_space: VowelSpace
    low_confidence: bool


def _speaking_samples(tracks: Tracks, phrases: list[Interval]) -> np.ndarray:
    parts = [tracks.samples[int(p.start_s * tracks.sr): int(p.end_s * tracks.sr)] for p in phrases]
    return np.concatenate(parts) if parts else np.array([])


def _hf_ratio(x: np.ndarray, sr: int, art: ArticulationConfig) -> float | None:
    nper = int(STFT_WINDOW_S * sr)
    hop = int(STFT_HOP_S * sr)
    if len(x) < nper:
        return None
    f, _, z = stft(x, fs=sr, window="hann", nperseg=nper, noverlap=nper - hop, boundary=None)
    power = np.abs(z) ** 2
    hf = power[(f >= art.hf_band_hz[0]) & (f <= art.hf_band_hz[1])].sum(axis=0)
    lf = power[(f >= art.lf_band_hz[0]) & (f <= art.lf_band_hz[1])].sum(axis=0)
    ok = lf > 0
    if not ok.any():
        return None
    return float(np.median(10 * np.log10(hf[ok] / lf[ok])))


def _tilt(x: np.ndarray, sr: int) -> float | None:
    if len(x) < WELCH_NPERSEG:
        return None
    f, p = welch(x, fs=sr, nperseg=WELCH_NPERSEG)
    m = (f >= TILT_BAND_HZ[0]) & (f <= TILT_BAND_HZ[1]) & (p > 0)
    if m.sum() < 3:
        return None
    slope, _ = np.polyfit(np.log2(f[m]), 10 * np.log10(p[m]), 1)
    return float(slope)


def _modulation_depth(tracks: Tracks, speaking: np.ndarray, acfg: AnalysisConfig, art: ArticulationConfig) -> float | None:
    if speaking.sum() < 10:
        return None
    fs = 1.0 / acfg.time_step_s
    linear = 10 ** (tracks.intensity_db / 20.0)
    sos = butter(2, [art.modulation_band_hz[0], art.modulation_band_hz[1]], btype="band", fs=fs, output="sos")
    if len(linear) <= 3 * (2 * 2 + 1):  # sosfiltfilt padlen guard
        return None
    band = sosfiltfilt(sos, linear)
    mean = float(np.mean(linear[speaking]))
    if mean <= 0:
        return None
    return float(np.sqrt(np.mean(band[speaking] ** 2)) / mean)


def _vowel_space(tracks: Tracks, art: ArticulationConfig) -> VowelSpace:
    empty = VowelSpace(f1_sd_hz=None, f2_sd_hz=None, vowel_space_area_hz2=None, vowel_dispersion_st=None)
    voiced_times = tracks.f0_times[~np.isnan(tracks.f0_hz)]
    if len(voiced_times) == 0:
        return empty
    formant = tracks.sound.to_formant_burg(
        time_step=FORMANT_TIME_STEP_S, max_number_of_formants=FORMANT_COUNT,
        maximum_formant=art.formant_max_hz, window_length=FORMANT_WINDOW_S,
        pre_emphasis_from=FORMANT_PREEMPHASIS_HZ,
    )
    f1 = np.array([formant.get_value_at_time(1, t) for t in voiced_times])
    f2 = np.array([formant.get_value_at_time(2, t) for t in voiced_times])
    ok = ~np.isnan(f1) & ~np.isnan(f2)
    f1, f2 = f1[ok], f2[ok]
    if len(f1) < 3:
        return empty
    lo, hi = art.formant_trim_pct, 100 - art.formant_trim_pct
    keep = (
        (f1 >= np.percentile(f1, lo)) & (f1 <= np.percentile(f1, hi))
        & (f2 >= np.percentile(f2, lo)) & (f2 <= np.percentile(f2, hi))
    )
    f1, f2 = f1[keep], f2[keep]
    if len(f1) < 3:
        return empty
    pts = np.column_stack([f1, f2])
    try:
        area = float(ConvexHull(pts).volume)
    except QhullError:
        area = 0.0
    c1, c2 = float(np.mean(f1)), float(np.mean(f2))
    dispersion = float(np.mean(np.sqrt(semitones(f1, c1) ** 2 + semitones(f2, c2) ** 2)))
    return VowelSpace(
        f1_sd_hz=float(np.std(f1)), f2_sd_hz=float(np.std(f2)),
        vowel_space_area_hz2=area, vowel_dispersion_st=dispersion,
    )


def compute(
    tracks: Tracks,
    acfg: AnalysisConfig,
    art: ArticulationConfig,
    phrases: list[Interval],
    peak_prominences_db: np.ndarray,
    f0_median_hz: float | None,
    recording_low_confidence: bool,
) -> ArticulationBlock:
    speech = _speaking_samples(tracks, phrases)
    speaking = speaking_mask(tracks, phrases)
    proms = np.asarray(peak_prominences_db, dtype=float)

    low_conf = recording_low_confidence or (f0_median_hz is not None and f0_median_hz > acfg.low_confidence_f0_hz)

    return ArticulationBlock(
        hf_energy_ratio_db=_hf_ratio(speech, tracks.sr, art) if len(speech) else None,
        spectral_tilt_db_per_oct=_tilt(speech, tracks.sr) if len(speech) else None,
        modulation_depth=_modulation_depth(tracks, speaking, acfg, art),
        syllable_peak_prominence_mean_db=float(np.mean(proms)) if len(proms) else None,
        syllable_peak_prominence_p25_db=float(np.percentile(proms, 25)) if len(proms) else None,
        weak_peak_fraction=float(np.mean(proms < art.weak_peak_prominence_db)) if len(proms) else None,
        vowel_space=_vowel_space(tracks, art) if phrases else VowelSpace(
            f1_sd_hz=None, f2_sd_hz=None, vowel_space_area_hz2=None, vowel_dispersion_st=None
        ),
        low_confidence=bool(low_conf),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_articulation.py -v`
Expected: 6 passed. If `test_two_vowels_have_larger_space_than_one` fails because the single-vowel area is not small enough for the `5×` margin, print both areas and lower the factor to `3`, not below; the direction of the inequality is the requirement.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/analysis/articulation.py backend/tests/test_articulation.py
git commit -m "feat(analysis): articulation proxies (spectral balance, modulation, vowel space)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Timeline windows

**Files:**
- Create: `backend/vocal_coach/analysis/timeline.py`
- Create: `backend/tests/test_timeline.py`

**Interfaces:**
- Consumes: `Tracks`, `AnalysisConfig`, `semitones`.
- Produces: `class TimelineWindow(BaseModel): start_s: float; end_s: float; f0_median_hz: float | None; f0_sd_st: float | None; intensity_median_db: float | None`; `class TimelineBlock(BaseModel): window_s: float; windows: list[TimelineWindow]`; `compute(tracks, cfg) -> TimelineBlock`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_timeline.py`:

```python
from tests import synth
from vocal_coach.analysis import timeline
from vocal_coach.analysis.tracks import extract_tracks


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def test_windows_cover_duration_and_track_pitch(cfg):
    x = synth.concat(synth.tone(100, 20.0), synth.tone(200, 20.0))
    blk = timeline.compute(_tracks(x, cfg), cfg.analysis)
    assert blk.window_s == 15
    assert len(blk.windows) == 3  # 0-15, 15-30, 30-40
    assert blk.windows[0].start_s == 0 and blk.windows[0].end_s == 15
    assert abs(blk.windows[2].end_s - 40.0) < 0.01
    assert abs(blk.windows[0].f0_median_hz - 100) < 2
    assert abs(blk.windows[2].f0_median_hz - 200) < 2
    assert blk.windows[0].f0_sd_st < 0.5
    assert blk.windows[1].f0_sd_st > 3  # contains the octave jump
    assert blk.windows[0].intensity_median_db is not None


def test_silent_window_has_null_f0(cfg):
    x = synth.concat(synth.tone(120, 15.0), synth.silence(15.0))
    blk = timeline.compute(_tracks(x, cfg), cfg.analysis)
    assert blk.windows[1].f0_median_hz is None
    assert blk.windows[1].f0_sd_st is None
    assert blk.windows[1].intensity_median_db is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_timeline.py -v`
Expected: FAIL with `ImportError: cannot import name 'timeline'`

- [ ] **Step 3: Implement timeline.py**

`backend/vocal_coach/analysis/timeline.py`:

```python
"""Per-window F0 and intensity summary."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vocal_coach.analysis.tracks import Tracks, semitones
from vocal_coach.config import AnalysisConfig


class TimelineWindow(BaseModel):
    start_s: float
    end_s: float
    f0_median_hz: float | None
    f0_sd_st: float | None
    intensity_median_db: float | None


class TimelineBlock(BaseModel):
    window_s: float
    windows: list[TimelineWindow]


def compute(tracks: Tracks, cfg: AnalysisConfig) -> TimelineBlock:
    windows: list[TimelineWindow] = []
    start = 0.0
    while start < tracks.duration_s:
        end = min(start + cfg.energy_window_s, tracks.duration_s)
        f0 = tracks.f0_between(start, end)
        inten = tracks.intensity_between(start, end)
        if len(f0):
            med = float(np.median(f0))
            sd = float(np.std(semitones(f0, med)))
        else:
            med, sd = None, None
        windows.append(TimelineWindow(
            start_s=float(start), end_s=float(end),
            f0_median_hz=med, f0_sd_st=sd,
            intensity_median_db=float(np.median(inten)) if len(inten) else None,
        ))
        start += cfg.energy_window_s
    return TimelineBlock(window_s=cfg.energy_window_s, windows=windows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_timeline.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/analysis/timeline.py backend/tests/test_timeline.py
git commit -m "feat(analysis): per-window timeline

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: MetricsReport schema, analyser, canonical serialisation, determinism, CLI

**Files:**
- Create: `backend/vocal_coach/analysis/schema.py`
- Create: `backend/vocal_coach/analysis/serialise.py`
- Create: `backend/vocal_coach/analysis/analyser.py`
- Create: `backend/tests/test_serialise.py`
- Create: `backend/tests/test_analyser.py`
- Create: `backend/tests/test_determinism.py`

**Interfaces:**
- Consumes: every block type from Tasks 4–11, `AudioInfo`, `extract_wav`, `AppConfig`, `config_hash`.
- Produces: `class SourceInfo(BaseModel): file_name: str; drive_file_id: str | None; drive_modified_time: str | None; content_sha256: str; duration_s: float; original_channels: int; original_sample_rate: int`; `class MetricsReport(BaseModel)` with fields `schema_version: str`, `analyser_version: str`, `config_hash: str`, `source: SourceInfo`, `recording_quality`, `pitch`, `phrasing`, `pace`, `intonation`, `energy`, `voice_quality`, `articulation`, `timeline`; `SCHEMA_VERSION = "1.0"`; `ANALYSER_VERSION = "0.1.0"`; `analyse_wav(wav_path: Path, cfg: AppConfig, source: SourceInfo) -> MetricsReport`; `analyse_file(src: Path, cfg: AppConfig, work_dir: Path, drive_file_id: str | None = None, drive_modified_time: str | None = None) -> MetricsReport`; `to_canonical_json(report: MetricsReport) -> str`; CLI `python -m vocal_coach.analysis.analyser <file> [--out metrics.json]`.

- [ ] **Step 1: Write the failing serialisation test**

`backend/tests/test_serialise.py`:

```python
import json
import math

from pydantic import BaseModel

from vocal_coach.analysis.serialise import round_floats, to_canonical_json


class Inner(BaseModel):
    voiced_fraction: float
    f0_median_hz: float
    maybe: float | None


class Outer(BaseModel):
    inner: Inner
    values: list[float]
    jitter_local: float


def test_round_floats_uses_six_decimals_for_ratio_fields_and_four_otherwise():
    data = {"voiced_fraction": 0.123456789, "f0_median_hz": 118.123456, "jitter_local": 0.0123456789,
            "values": [1.23456789, 2.0], "nested": {"modulation_depth": 0.98765432}}
    out = round_floats(data)
    assert out["voiced_fraction"] == 0.123457
    assert out["f0_median_hz"] == 118.1235
    assert out["jitter_local"] == 0.012346
    assert out["values"] == [1.2346, 2.0]
    assert out["nested"]["modulation_depth"] == 0.987654


def test_nan_and_inf_become_null():
    out = round_floats({"a": math.nan, "b": math.inf, "c": [math.nan, 1.0]})
    assert out == {"a": None, "b": None, "c": [None, 1.0]}


def test_canonical_json_sorted_and_compact():
    obj = Outer(inner=Inner(voiced_fraction=0.5, f0_median_hz=100.0, maybe=None), values=[1.0], jitter_local=0.01)
    s = to_canonical_json(obj)
    assert s == json.dumps(json.loads(s), sort_keys=True, separators=(",", ":"))
    assert "\n" not in s and " " not in s
    assert '"maybe":null' in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_serialise.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.analysis.serialise'`

- [ ] **Step 3: Implement serialise.py**

`backend/vocal_coach/analysis/serialise.py`:

```python
"""Canonical, byte-stable JSON for metrics reports."""
from __future__ import annotations

import json
import math
from typing import Any

from pydantic import BaseModel

SIX_DECIMAL_FIELDS = frozenset({
    "voiced_fraction", "creak_fraction_below_100hz", "jitter_local", "shimmer_local",
    "modulation_depth", "weak_peak_fraction",
})
DEFAULT_DECIMALS = 4
RATIO_DECIMALS = 6


def _round(value: float, decimals: int) -> float | None:
    if not math.isfinite(value):
        return None
    r = round(value, decimals)
    return 0.0 if r == 0 else r  # normalise -0.0


def round_floats(obj: Any, decimals: int = DEFAULT_DECIMALS) -> Any:
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return _round(obj, decimals)
    if isinstance(obj, dict):
        return {
            k: round_floats(v, RATIO_DECIMALS if k in SIX_DECIMAL_FIELDS else DEFAULT_DECIMALS)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [round_floats(v, decimals) for v in obj]
    return obj


def to_canonical_json(report: BaseModel) -> str:
    data = round_floats(report.model_dump(mode="json", by_alias=True))
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
```

- [ ] **Step 4: Run serialisation test**

Run: `pytest tests/test_serialise.py -v`
Expected: 3 passed

- [ ] **Step 5: Write the failing analyser and determinism tests**

`backend/tests/test_analyser.py`:

```python
import json
from pathlib import Path

from tests import synth
from tests.conftest import requires_ffmpeg
from vocal_coach.analysis.analyser import ANALYSER_VERSION, analyse_file, analyse_wav
from vocal_coach.analysis.schema import SCHEMA_VERSION, MetricsReport, SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.config import config_hash


def _speechlike(dur_each=3.0):
    a = synth.am(synth.vowel(500, 1500, 120, dur_each), 4.0)
    b = synth.am(synth.vowel(300, 2300, 130, dur_each), 4.5)
    return synth.with_noise_floor(synth.concat(a, synth.silence(0.6), b, synth.silence(1.2), a))


def _source(path: Path, dur: float) -> SourceInfo:
    return SourceInfo(file_name=path.name, drive_file_id=None, drive_modified_time=None,
                      content_sha256="x" * 64, duration_s=dur, original_channels=1, original_sample_rate=16000)


def test_analyse_wav_produces_full_report(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", _speechlike())
    report = analyse_wav(wav, cfg, _source(wav, 10.8))
    assert isinstance(report, MetricsReport)
    assert report.schema_version == SCHEMA_VERSION == "1.0"
    assert report.analyser_version == ANALYSER_VERSION == "0.1.0"
    assert report.config_hash == config_hash(cfg)
    assert report.phrasing.phrase_count == 3
    assert report.phrasing.long_pause_count_ge_1s == 1
    assert report.pitch.f0_median_hz is not None
    assert report.pace.syllable_count_est > 20
    assert len(report.timeline.windows) == 1
    assert report.recording_quality.low_confidence is False
    data = json.loads(to_canonical_json(report))
    assert set(data) == {"schema_version", "analyser_version", "config_hash", "source", "recording_quality",
                         "pitch", "phrasing", "pace", "intonation", "energy", "voice_quality",
                         "articulation", "timeline"}
    assert "class" in data["intonation"]["per_phrase"][0]


def test_silence_does_not_raise(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "quiet.wav", synth.with_noise_floor(synth.silence(4.0)))
    report = analyse_wav(wav, cfg, _source(wav, 4.0))
    assert "no_voiced_speech" in report.recording_quality.reasons
    assert report.recording_quality.low_confidence is True
    assert report.pitch.f0_median_hz is None
    assert report.phrasing.phrase_count == 0
    to_canonical_json(report)  # must serialise without NaN errors


@requires_ffmpeg
def test_analyse_file_extracts_then_analyses(cfg, tmp_path: Path):
    src = synth.write_wav(tmp_path / "in.wav", _speechlike())
    report = analyse_file(src, cfg, work_dir=tmp_path / "work", drive_file_id="abc", drive_modified_time="2026-10-01T00:00:00Z")
    assert report.source.file_name == "in.wav"
    assert report.source.drive_file_id == "abc"
    assert report.source.original_sample_rate == 16000
    assert len(report.source.content_sha256) == 64
    assert (tmp_path / "work" / "in.wav").exists()
```

`backend/tests/test_determinism.py`:

```python
import subprocess
import sys
from pathlib import Path

from tests import synth
from tests.conftest import requires_ffmpeg


def _speechlike():
    a = synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)
    b = synth.am(synth.vowel(300, 2300, 130, 3.0), 4.5)
    return synth.with_noise_floor(synth.concat(a, synth.silence(0.6), b, synth.silence(1.2), a))


@requires_ffmpeg
def test_two_runs_in_separate_processes_are_byte_identical(tmp_path: Path):
    src = synth.write_wav(tmp_path / "in.wav", _speechlike())
    outs = []
    for i in range(2):
        out = tmp_path / f"metrics_{i}.json"
        subprocess.run(
            [sys.executable, "-m", "vocal_coach.analysis.analyser", str(src), "--out", str(out),
             "--work-dir", str(tmp_path / f"work{i}")],
            check=True,
        )
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]
    assert len(outs[0]) > 1000
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_analyser.py tests/test_determinism.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.analysis.analyser'`

- [ ] **Step 7: Implement schema.py**

`backend/vocal_coach/analysis/schema.py`:

```python
"""Versioned metrics report schema."""
from __future__ import annotations

from pydantic import BaseModel

from vocal_coach.analysis.articulation import ArticulationBlock
from vocal_coach.analysis.energy import EnergyBlock
from vocal_coach.analysis.intonation import IntonationBlock
from vocal_coach.analysis.pace import PaceBlock
from vocal_coach.analysis.phrasing import PhrasingBlock
from vocal_coach.analysis.pitch import PitchBlock
from vocal_coach.analysis.quality import RecordingQualityBlock
from vocal_coach.analysis.timeline import TimelineBlock
from vocal_coach.analysis.voice_quality import VoiceQualityBlock

SCHEMA_VERSION = "1.0"


class SourceInfo(BaseModel):
    file_name: str
    drive_file_id: str | None
    drive_modified_time: str | None
    content_sha256: str
    duration_s: float
    original_channels: int
    original_sample_rate: int


class MetricsReport(BaseModel):
    schema_version: str
    analyser_version: str
    config_hash: str
    source: SourceInfo
    recording_quality: RecordingQualityBlock
    pitch: PitchBlock
    phrasing: PhrasingBlock
    pace: PaceBlock
    intonation: IntonationBlock
    energy: EnergyBlock
    voice_quality: VoiceQualityBlock
    articulation: ArticulationBlock
    timeline: TimelineBlock
```

- [ ] **Step 8: Implement analyser.py**

`backend/vocal_coach/analysis/analyser.py`:

```python
"""Run every analysis module on a WAV and assemble a MetricsReport. Also a CLI."""
from __future__ import annotations

import argparse
from pathlib import Path

import parselmouth

from vocal_coach.analysis import (
    articulation, energy, intonation, pace, phrasing, pitch, quality, timeline, voice_quality,
)
from vocal_coach.analysis.audio import extract_wav
from vocal_coach.analysis.schema import SCHEMA_VERSION, MetricsReport, SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.config import AppConfig, config_hash, load_config

ANALYSER_VERSION = "0.1.0"


def analyse_wav(wav_path: Path, cfg: AppConfig, source: SourceInfo) -> MetricsReport:
    sound = parselmouth.Sound(str(wav_path))
    tracks = extract_tracks(sound, cfg.analysis)

    phr = phrasing.compute(tracks, cfg.analysis)
    rq = quality.compute(tracks, cfg.analysis, phr.phrases)
    pit = pitch.compute(tracks, cfg.analysis)
    pac = pace.compute(tracks, cfg.analysis, phr.block.speaking_time_s)
    into = intonation.compute(tracks, cfg.analysis, phr.phrases)
    ene = energy.compute(tracks, cfg.analysis, phr.phrases)
    vq = voice_quality.compute(tracks, cfg.analysis, rq.low_confidence)
    art = articulation.compute(
        tracks, cfg.analysis, cfg.articulation, phr.phrases,
        pac.peak_prominences_db, pit.f0_median_hz, rq.low_confidence,
    )
    tl = timeline.compute(tracks, cfg.analysis)

    return MetricsReport(
        schema_version=SCHEMA_VERSION,
        analyser_version=ANALYSER_VERSION,
        config_hash=config_hash(cfg),
        source=source,
        recording_quality=rq,
        pitch=pit,
        phrasing=phr.block,
        pace=pac.block,
        intonation=into,
        energy=ene,
        voice_quality=vq,
        articulation=art,
        timeline=tl,
    )


def analyse_file(
    src: Path,
    cfg: AppConfig,
    work_dir: Path,
    drive_file_id: str | None = None,
    drive_modified_time: str | None = None,
) -> MetricsReport:
    work_dir.mkdir(parents=True, exist_ok=True)
    wav = work_dir / (src.stem + ".wav")
    info = extract_wav(src, wav)
    source = SourceInfo(
        file_name=src.name,
        drive_file_id=drive_file_id,
        drive_modified_time=drive_modified_time,
        content_sha256=info.content_sha256,
        duration_s=info.duration_s,
        original_channels=info.original_channels,
        original_sample_rate=info.original_sample_rate,
    )
    return analyse_wav(wav, cfg, source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyse a recording and write metrics JSON.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="Output path (default: stdout)")
    parser.add_argument("--work-dir", type=Path, default=Path("data/work"))
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    report = analyse_file(args.file, cfg, args.work_dir)
    text = to_canonical_json(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 9: Run all tests**

Run: `pytest -v`
Expected: all tests in `tests/` pass, including `test_two_runs_in_separate_processes_are_byte_identical`. If the determinism test fails, diff the two JSON files; the only legitimate sources of difference are float formatting (fix rounding in `serialise.py`) or thread-dependent numpy reductions (set `OMP_NUM_THREADS=1` inside `main()` via `os.environ.setdefault` before importing numpy and re-run).

- [ ] **Step 10: Smoke the CLI on a real file**

Run from `backend/` with any real recording you have (`.m4a`, `.mp3`, `.mp4`):

```bash
python -m vocal_coach.analysis.analyser /path/to/recording.m4a --out data/metrics.json && python -c "import json;d=json.load(open('data/metrics.json'));print(d['pitch'], d['phrasing']['phrase_count'], d['articulation']['hf_energy_ratio_db'])"
```

Expected: a JSON file and printed plausible values (median F0 85–300 Hz for speech, phrase count > 0). No real file available → skip this step and say so in the task report.

- [ ] **Step 11: Commit**

```bash
git add backend/vocal_coach/analysis/schema.py backend/vocal_coach/analysis/serialise.py backend/vocal_coach/analysis/analyser.py backend/tests/test_serialise.py backend/tests/test_analyser.py backend/tests/test_determinism.py
git commit -m "feat(analysis): MetricsReport, canonical JSON, analyser pipeline, CLI and determinism test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Backend README for the analysis core

**Files:**
- Create: `backend/README.md`

**Interfaces:** none.

- [ ] **Step 1: Write the README**

`backend/README.md`:

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add backend/README.md
git commit -m "docs(backend): analysis core setup and run instructions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage (§6):** audio extraction → Task 2; fixed parameters + config_hash → Task 1; recording_quality → Task 9; pitch → 4; phrasing → 5; pace → 6; intonation → 7; energy → 8; voice_quality → 9; articulation → 10; timeline → 11; schema + serialisation rules → 12. §16 analysis tests all present. Sections §7–§15 belong to later plans.
- **Deviation from spec, deliberate:** spec says `compute(sound, cfg, **deps)`; this plan passes a `Tracks` object instead so F0/intensity are extracted once. Spec also lists `recording_quality` as computed in `analyser.py`; here it has its own `quality.py` so it is testable alone. Both are internal to `analysis/` and change no output field.
- **Type consistency:** `Interval` defined in Task 5 and consumed by 7, 8, 9, 10; `speaking_mask` defined in Task 8 and consumed by 9, 10; `PaceResult.peak_prominences_db` (Task 6) consumed by Task 10; all block class names in Task 12's `schema.py` match their defining tasks.
- **Review Focus items** pinned: 1 → `test_silence_does_not_raise` (Task 12); 2 → `test_long_leading_silence_gives_null_opening` (Task 4); 3 → `test_phrase_with_unvoiced_tail_is_unclassified` (Task 7); 4 → `test_short_recording_body_falls_back_to_all_speech` (Task 8); 5 → `test_extract_from_mp4_container` (Task 2).
