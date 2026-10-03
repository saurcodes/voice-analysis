# Vocal Coach — Plan 2: Transcription and Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a 16 kHz WAV into a `transcript.json` with word timestamps, filler counts, words-per-minute and clarity proxies (low-confidence, half-eaten, rushed words), using faster-whisper with fixed decoding settings.

**Architecture:** A new `backend/vocal_coach/transcription/` package beside `analysis/`. `transcriber.py` wraps faster-whisper behind a tiny model interface so tests inject a fake model and never download weights. `fillers.py` and `syllables.py` are pure text functions. `clarity.py` combines whisper word boundaries with the intensity contour from `analysis.tracks.Tracks` (reused, not recomputed, when the caller already has it). `run.py` assembles the `Transcript` pydantic document and exposes a CLI. Transcript-derived numbers stay out of `metrics.json`: they live in `transcript.json`, serialised with the same canonical rules.

**Tech Stack:** Python 3.11+, faster-whisper (CTranslate2, CPU int8), pydantic 2, numpy, praat-parselmouth (via existing `Tracks`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-vocal-coach-design.md` — this plan implements §7 (Transcription) and §7.1 (`transcript.json` schema); §16 rows `test_clarity`, `test_fillers`.

## Global Constraints

- Python ≥ 3.11. Package at `backend/vocal_coach/transcription`; tests at `backend/tests`; run everything from `backend/` with `.venv` activated.
- Transcription and clarity parameters come from `backend/config.yaml` sections `transcription` and `clarity` (values already present: `model_size: small`, `compute_type: int8`, `beam_size: 5`, `language: en`, `fillers: [um, uh, like, basically, actually, "you know", so]`; `low_conf_word_prob: 0.5`, `word_final_drop_db: 6`, `word_final_tail_fraction: 0.3`, `min_word_duration_s: 0.25`, `rushed_syl_per_sec: 7`, `rushed_run_min_words: 3`, `low_logprob_segment: -1.0`). No numeric threshold literal inside `transcription/*.py`; algorithm constants are named module-level constants with a comment.
- `config_hash` must NOT change: it covers only `analysis` + `articulation`. Adding `transcription`/`clarity` pydantic sections to `AppConfig` is required; hashing them is forbidden.
- Whisper decoding is fixed: `temperature=0.0`, `beam_size` from config, `word_timestamps=True`, `vad_filter=False`, `language` from config (`null` → auto-detect).
- `transcript.json`: `schema_version "1.0"`, shape exactly as spec §7.1, serialised with `vocal_coach.analysis.serialise.to_canonical_json` (4 decimals; probabilities and fractions are ratio fields → 6 decimals: add `probability`, `avg_logprob`, `no_speech_prob`, `low_conf_word_fraction`, `word_final_drop_fraction`, `rushed_word_fraction`, `low_logprob_segment_fraction` to `SIX_DECIMAL_FIELDS`).
- Tests never load real whisper weights or touch the network. The real-model path is exercised only by an opt-in test gated on `VOCAL_COACH_REAL_WHISPER=1` and by the controller's smoke run.
- Test output pristine under `pytest -v -W error`.
- Commit after every task; messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **Whisper returns a word with zero or negative duration** (`end <= start`, happens on clipped tokens): rate-based metrics must skip it, never divide by zero. Test in Task 4.
2. **Word timestamps past the end of the audio** (whisper overshoots on trailing silence): `intensity_between` returns empty → the word is skipped for the drop metric, never raises. Test in Task 4.
3. **Whisper finds no speech at all** (music, silence): `Transcript` with empty lists, `word_count 0`, `words_per_min 0.0`, fractions `None`, and it serialises. Test in Task 6.
4. **Tokens with no vowels or only punctuation** ("hmm", "—", "2024"): syllable count is at least 1 for a real token; punctuation-only tokens are dropped before counting. Test in Task 2.
5. **Multi-word filler split by case, punctuation or a segment boundary** ("You know," at the end of one segment and "know" starting the next): still counted once. Test in Task 3.

---

### Task 1: Config sections for transcription and clarity

**Files:**
- Modify: `backend/vocal_coach/config.py`
- Modify: `backend/vocal_coach/analysis/serialise.py` (extend `SIX_DECIMAL_FIELDS`)
- Test: `backend/tests/test_config.py` (append)

**Interfaces:**
- Consumes: existing `AppConfig`, `load_config`, `config_hash`, `SIX_DECIMAL_FIELDS`.
- Produces: `class TranscriptionConfig(BaseModel)`: `model_size: str`, `compute_type: str`, `beam_size: int`, `language: str | None`, `fillers: list[str]`; `class ClarityConfig(BaseModel)`: `low_conf_word_prob: float`, `word_final_drop_db: float`, `word_final_tail_fraction: float`, `min_word_duration_s: float`, `rushed_syl_per_sec: float`, `rushed_run_min_words: int`, `low_logprob_segment: float`; `AppConfig.transcription: TranscriptionConfig`, `AppConfig.clarity: ClarityConfig`.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_config.py`)

```python
def test_transcription_and_clarity_sections_load():
    cfg = load_config()
    assert cfg.transcription.model_size == "small"
    assert cfg.transcription.compute_type == "int8"
    assert cfg.transcription.beam_size == 5
    assert cfg.transcription.language == "en"
    assert cfg.transcription.fillers == ["um", "uh", "like", "basically", "actually", "you know", "so"]
    assert cfg.clarity.low_conf_word_prob == 0.5
    assert cfg.clarity.word_final_drop_db == 6
    assert cfg.clarity.word_final_tail_fraction == 0.3
    assert cfg.clarity.min_word_duration_s == 0.25
    assert cfg.clarity.rushed_syl_per_sec == 7
    assert cfg.clarity.rushed_run_min_words == 3
    assert cfg.clarity.low_logprob_segment == -1.0


def test_config_hash_ignores_transcription_and_clarity():
    src = load_config()
    changed = src.model_copy(deep=True)
    changed.transcription.beam_size = 1
    changed.clarity.rushed_syl_per_sec = 99
    assert config_hash(src) == config_hash(changed)


def test_six_decimal_fields_include_transcript_ratios():
    from vocal_coach.analysis.serialise import SIX_DECIMAL_FIELDS
    for name in ("probability", "avg_logprob", "no_speech_prob", "low_conf_word_fraction",
                 "word_final_drop_fraction", "rushed_word_fraction", "low_logprob_segment_fraction"):
        assert name in SIX_DECIMAL_FIELDS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: 3 new tests FAIL with `AttributeError: 'AppConfig' object has no attribute 'transcription'` / assertion on `SIX_DECIMAL_FIELDS`.

- [ ] **Step 3: Implement**

In `backend/vocal_coach/config.py`, add after `ArticulationConfig`:

```python
class TranscriptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_size: str
    compute_type: str
    beam_size: int
    language: str | None
    fillers: list[str]


class ClarityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_conf_word_prob: float
    word_final_drop_db: float
    word_final_tail_fraction: float
    min_word_duration_s: float
    rushed_syl_per_sec: float
    rushed_run_min_words: int
    low_logprob_segment: float
```

Extend `AppConfig`:

```python
class AppConfig(BaseModel):
    analysis: AnalysisConfig
    articulation: ArticulationConfig
    transcription: TranscriptionConfig
    clarity: ClarityConfig
    raw: dict[str, Any]
```

Extend `load_config` to pass `transcription=TranscriptionConfig(**raw["transcription"])` and `clarity=ClarityConfig(**raw["clarity"])`. Leave `config_hash` untouched (it reads only `analysis` and `articulation`).

In `backend/vocal_coach/analysis/serialise.py` extend the set:

```python
SIX_DECIMAL_FIELDS = frozenset({
    "voiced_fraction", "creak_fraction_below_100hz", "jitter_local", "shimmer_local",
    "modulation_depth", "weak_peak_fraction",
    # transcript.json ratio fields
    "probability", "avg_logprob", "no_speech_prob",
    "low_conf_word_fraction", "word_final_drop_fraction", "rushed_word_fraction",
    "low_logprob_segment_fraction",
})
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_config.py tests/test_serialise.py tests/test_determinism.py -v -W error`
Expected: all pass (determinism unaffected: no metrics key is in the added set).

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/config.py backend/vocal_coach/analysis/serialise.py backend/tests/test_config.py
git commit -m "feat(config): transcription and clarity config sections

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Transcript schema and syllable counter

**Files:**
- Create: `backend/vocal_coach/transcription/__init__.py` (empty)
- Create: `backend/vocal_coach/transcription/schema.py`
- Create: `backend/vocal_coach/transcription/syllables.py`
- Create: `backend/tests/test_syllables.py`

**Interfaces:**
- Produces (`schema.py`): `TRANSCRIPT_SCHEMA_VERSION = "1.0"`; `class TranscriptWord(BaseModel): start_s: float; end_s: float; word: str; probability: float`; `class TranscriptSegment(BaseModel): start_s: float; end_s: float; text: str; avg_logprob: float; no_speech_prob: float`; `class Span(BaseModel): start_s: float; end_s: float; text: str`; `class LowConfWord(BaseModel): start_s: float; end_s: float; word: str; probability: float`; `class EatenWord(BaseModel): start_s: float; end_s: float; word: str; drop_db: float`; `class ClarityBlock(BaseModel)` with `low_conf_word_fraction: float | None`, `low_conf_words: list[LowConfWord]`, `word_final_drop_count: int`, `word_final_drop_fraction: float | None`, `eaten_words: list[EatenWord]`, `rushed_word_fraction: float | None`, `rushed_runs: list[Span]`, `segment_avg_logprob_mean: float | None`, `low_logprob_segment_fraction: float | None`; `class DerivedBlock(BaseModel)`: `word_count: int`, `words_per_min: float`, `filler_counts: dict[str, int]`, `filler_total: int`, `fillers_per_min: float`, `clarity: ClarityBlock`; `class Transcript(BaseModel)`: `schema_version: str`, `model: str`, `language: str | None`, `text: str`, `segments: list[TranscriptSegment]`, `words: list[TranscriptWord]`, `derived: DerivedBlock`.
- Produces (`syllables.py`): `normalise_token(word: str) -> str` (lowercase, strip surrounding whitespace and punctuation, keep internal apostrophes); `count_syllables(word: str) -> int` (0 for a token that normalises to empty, else ≥ 1).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_syllables.py`:

```python
import pytest

from vocal_coach.transcription.syllables import count_syllables, normalise_token


@pytest.mark.parametrize("raw, expected", [
    (" Hello,", "hello"),
    ("YOU", "you"),
    ("don't", "don't"),
    ("...", ""),
    ("—", ""),
    (" 2024 ", "2024"),
])
def test_normalise_token(raw, expected):
    assert normalise_token(raw) == expected


@pytest.mark.parametrize("word, expected", [
    ("cat", 1),
    ("basically", 4),
    ("actually", 3),   # heuristic undercounts the mid-word "ua" hiatus; accepted, documented
    ("the", 1),
    ("table", 2),      # trailing 'le' after a consonant counts
    ("make", 1),       # silent trailing e
    ("idea", 3),
    ("hmm", 1),        # no vowels: still one syllable
    ("2024", 1),       # digits: one token, one syllable
    ("...", 0),        # punctuation only
    ("you", 1),
    ("beautiful", 3),
])
def test_count_syllables(word, expected):
    assert count_syllables(word) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_syllables.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.transcription'`

- [ ] **Step 3: Implement schema.py and syllables.py**

`backend/vocal_coach/transcription/schema.py`:

```python
"""transcript.json document model (spec §7.1)."""
from __future__ import annotations

from pydantic import BaseModel

TRANSCRIPT_SCHEMA_VERSION = "1.0"


class TranscriptWord(BaseModel):
    start_s: float
    end_s: float
    word: str
    probability: float


class TranscriptSegment(BaseModel):
    start_s: float
    end_s: float
    text: str
    avg_logprob: float
    no_speech_prob: float


class Span(BaseModel):
    start_s: float
    end_s: float
    text: str


class LowConfWord(BaseModel):
    start_s: float
    end_s: float
    word: str
    probability: float


class EatenWord(BaseModel):
    start_s: float
    end_s: float
    word: str
    drop_db: float


class ClarityBlock(BaseModel):
    low_conf_word_fraction: float | None
    low_conf_words: list[LowConfWord]
    word_final_drop_count: int
    word_final_drop_fraction: float | None
    eaten_words: list[EatenWord]
    rushed_word_fraction: float | None
    rushed_runs: list[Span]
    segment_avg_logprob_mean: float | None
    low_logprob_segment_fraction: float | None


class DerivedBlock(BaseModel):
    word_count: int
    words_per_min: float
    filler_counts: dict[str, int]
    filler_total: int
    fillers_per_min: float
    clarity: ClarityBlock


class Transcript(BaseModel):
    schema_version: str
    model: str
    language: str | None
    text: str
    segments: list[TranscriptSegment]
    words: list[TranscriptWord]
    derived: DerivedBlock
```

`backend/vocal_coach/transcription/syllables.py`:

```python
"""Deterministic English syllable estimate from spelling. No dictionary."""
from __future__ import annotations

import re

VOWELS = "aeiouy"
_STRIP_RE = re.compile(r"^[^a-z0-9']+|[^a-z0-9']+$")  # leading/trailing punctuation
_VOWEL_GROUP_RE = re.compile(rf"[{VOWELS}]+")
MIN_SYLLABLES_FOR_TOKEN = 1  # any real token has at least one nucleus, even "hmm"
HIATUS_ENDINGS = ("ia", "ea", "io", "ua")  # "idea", "media", "radio": the final two vowels are separate nuclei


def normalise_token(word: str) -> str:
    return _STRIP_RE.sub("", word.strip().lower()).strip("'")


def count_syllables(word: str) -> int:
    w = normalise_token(word)
    if not w:
        return 0
    groups = len(_VOWEL_GROUP_RE.findall(w))
    # Silent trailing 'e' ("make"), but keep consonant+"le" ("table").
    if w.endswith("e") and not w.endswith("le") and groups > 1 and w[-2] not in VOWELS:
        groups -= 1
    if w.endswith(HIATUS_ENDINGS):
        groups += 1
    return max(MIN_SYLLABLES_FOR_TOKEN, groups)
```

Worked examples the test pins: "table" → groups "a","e" = 2 (ends in "le", so no silent-e subtraction) → 2. "make" → 2, ends in "e" not "le", "k" is a consonant → 1. "idea" → "i","ea" = 2, hiatus ending → 3. "beautiful" → "eau","i","u" → 3. "actually" → "a","ua","y" → 3 (the mid-word "ua" hiatus is undercounted; the test documents this). "hmm" → 0 groups → 1. "2024" → 1. "..." → "" → 0.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_syllables.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/transcription/__init__.py backend/vocal_coach/transcription/schema.py backend/vocal_coach/transcription/syllables.py backend/tests/test_syllables.py
git commit -m "feat(transcription): transcript schema and syllable estimate

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Fillers and words-per-minute

**Files:**
- Create: `backend/vocal_coach/transcription/fillers.py`
- Create: `backend/tests/test_fillers.py`

**Interfaces:**
- Consumes: `TranscriptWord`, `normalise_token`.
- Produces: `count_fillers(words: list[TranscriptWord], fillers: list[str]) -> dict[str, int]` (keys in config order, all present even when 0; multi-word fillers matched on consecutive normalised tokens, non-overlapping, greedy left-to-right, longest filler first); `words_per_min(word_count: int, duration_s: float) -> float` (0.0 when duration ≤ 0); `per_min(count: int, duration_s: float) -> float`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_fillers.py`:

```python
from vocal_coach.transcription.fillers import count_fillers, per_min, words_per_min
from vocal_coach.transcription.schema import TranscriptWord

FILLERS = ["um", "uh", "like", "basically", "actually", "you know", "so"]


def _words(*tokens: str) -> list[TranscriptWord]:
    return [TranscriptWord(start_s=i * 0.3, end_s=i * 0.3 + 0.25, word=t, probability=0.9) for i, t in enumerate(tokens)]


def test_counts_single_and_multiword_fillers():
    words = _words(" Um,", "so", "I", "was,", "like,", "You", "know,", "basically", "done", "uh")
    counts = count_fillers(words, FILLERS)
    assert counts == {"um": 1, "uh": 1, "like": 1, "basically": 1, "actually": 0, "you know": 1, "so": 1}


def test_multiword_filler_across_segment_boundary_and_case():
    # "You" ends one whisper segment, "know." starts the next; tokens are still adjacent in the word list.
    words = _words("and", "You", "know.", "that")
    assert count_fillers(words, FILLERS)["you know"] == 1


def test_multiword_consumes_tokens_so_singles_do_not_double_count():
    words = _words("you", "know", "you")
    counts = count_fillers(words, ["you know", "you"])
    assert counts == {"you know": 1, "you": 1}


def test_all_keys_present_when_no_fillers():
    assert count_fillers(_words("clean", "speech"), FILLERS) == {f: 0 for f in FILLERS}


def test_rates():
    assert abs(words_per_min(120, 60.0) - 120.0) < 1e-9
    assert words_per_min(5, 0.0) == 0.0
    assert abs(per_min(3, 30.0) - 6.0) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fillers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.transcription.fillers'`

- [ ] **Step 3: Implement fillers.py**

```python
"""Filler-word counts and per-minute rates over whisper words."""
from __future__ import annotations

from vocal_coach.transcription.schema import TranscriptWord
from vocal_coach.transcription.syllables import normalise_token

SECONDS_PER_MINUTE = 60.0


def per_min(count: int, duration_s: float) -> float:
    return float(count / (duration_s / SECONDS_PER_MINUTE)) if duration_s > 0 else 0.0


def words_per_min(word_count: int, duration_s: float) -> float:
    return per_min(word_count, duration_s)


def count_fillers(words: list[TranscriptWord], fillers: list[str]) -> dict[str, int]:
    tokens = [normalise_token(w.word) for w in words]
    tokens = [t for t in tokens if t]
    patterns = [tuple(normalise_token(p) for p in f.split()) for f in fillers]
    # Longest patterns first so "you know" wins over "you".
    order = sorted(range(len(fillers)), key=lambda i: -len(patterns[i]))
    counts = {f: 0 for f in fillers}
    i = 0
    while i < len(tokens):
        matched = False
        for idx in order:
            pat = patterns[idx]
            n = len(pat)
            if tuple(tokens[i:i + n]) == pat:
                counts[fillers[idx]] += 1
                i += n
                matched = True
                break
        if not matched:
            i += 1
    return counts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fillers.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/transcription/fillers.py backend/tests/test_fillers.py
git commit -m "feat(transcription): filler counts and per-minute rates

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Clarity metrics

**Files:**
- Create: `backend/vocal_coach/transcription/clarity.py`
- Create: `backend/tests/test_clarity.py`

**Interfaces:**
- Consumes: `Tracks.intensity_between`, `ClarityConfig`, `TranscriptWord`, `TranscriptSegment`, `count_syllables`, schema blocks.
- Produces: `compute(words: list[TranscriptWord], segments: list[TranscriptSegment], tracks: Tracks, cfg: ClarityConfig) -> ClarityBlock`.

Definitions (spec §7):
- `low_conf_words`: words with `probability < low_conf_word_prob`; fraction over all words (`None` if no words).
- Word-final drop: for words with `end_s - start_s >= min_word_duration_s`: head = intensity over `[start, end - tail_fraction·dur]`, tail = intensity over `[end - tail_fraction·dur, end]`; skip if either is empty (e.g. timestamp past audio end); `drop_db = median(tail) - median(head)`; eaten if `drop_db < -word_final_drop_db`. `word_final_drop_fraction` = eaten / eligible-with-data (`None` if none eligible).
- Rushed: for words with `dur > 0`: `count_syllables(word) / dur > rushed_syl_per_sec`; fraction over words with `dur > 0` (`None` if none). Runs: ≥ `rushed_run_min_words` consecutive rushed words (consecutive in the word list) → `Span(start_s of first, end_s of last, text joined by single spaces using the raw stripped words)`.
- `segment_avg_logprob_mean`: mean of `avg_logprob` (`None` if no segments); `low_logprob_segment_fraction`: share with `avg_logprob < low_logprob_segment` (`None` if no segments).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_clarity.py`:

```python
import numpy as np

from tests import synth
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.transcription import clarity
from vocal_coach.transcription.schema import TranscriptSegment, TranscriptWord


def _tracks(x, cfg):
    return extract_tracks(synth.to_sound(synth.with_noise_floor(x)), cfg.analysis)


def _w(start, end, word, prob=0.95):
    return TranscriptWord(start_s=start, end_s=end, word=word, probability=prob)


def _seg(start, end, text, logprob=-0.3):
    return TranscriptSegment(start_s=start, end_s=end, text=text, avg_logprob=logprob, no_speech_prob=0.01)


def test_eaten_word_detected_by_tail_drop(cfg):
    # word A: 0.0–0.6 s steady; word B: 0.7–1.3 s with last 30 % attenuated 10 dB.
    a = synth.tone(120, 0.6)
    b = synth.attenuate_tail(synth.tone(120, 0.6), tail_s=0.18, db=10)
    x = synth.concat(a, synth.silence(0.1), b)
    words = [_w(0.0, 0.6, "steady"), _w(0.7, 1.3, "eaten")]
    blk = clarity.compute(words, [_seg(0.0, 1.3, "steady eaten")], _tracks(x, cfg), cfg.clarity)
    assert blk.word_final_drop_count == 1
    assert blk.eaten_words[0].word == "eaten"
    assert blk.eaten_words[0].drop_db < -6
    assert abs(blk.word_final_drop_fraction - 0.5) < 1e-9


def test_short_words_not_eligible_for_drop(cfg):
    x = synth.tone(120, 1.0)
    words = [_w(0.0, 0.2, "a"), _w(0.2, 0.4, "to")]  # both < min_word_duration_s 0.25
    blk = clarity.compute(words, [_seg(0.0, 0.4, "a to")], _tracks(x, cfg), cfg.clarity)
    assert blk.word_final_drop_count == 0
    assert blk.word_final_drop_fraction is None


def test_word_past_audio_end_is_skipped_not_raised(cfg):
    x = synth.tone(120, 1.0)
    words = [_w(0.0, 0.6, "ok"), _w(1.5, 2.2, "ghost")]  # second word entirely after the 1.0 s audio
    blk = clarity.compute(words, [_seg(0.0, 2.2, "ok ghost")], _tracks(x, cfg), cfg.clarity)
    assert blk.word_final_drop_count == 0
    assert abs(blk.word_final_drop_fraction - 0.0) < 1e-9  # one eligible word with data, not eaten


def test_low_confidence_words(cfg):
    x = synth.tone(120, 1.0)
    words = [_w(0.0, 0.3, "clear", 0.9), _w(0.3, 0.6, "mumble", 0.2), _w(0.6, 0.9, "ok", 0.6)]
    blk = clarity.compute(words, [_seg(0.0, 0.9, "clear mumble ok")], _tracks(x, cfg), cfg.clarity)
    assert [w.word for w in blk.low_conf_words] == ["mumble"]
    assert abs(blk.low_conf_word_fraction - 1 / 3) < 1e-9


def test_rushed_words_and_runs(cfg):
    x = synth.tone(120, 2.0)
    # "basically" (4 syl) in 0.3 s = 13.3 syl/s → rushed; three in a row form a run; a slow word breaks it.
    words = [
        _w(0.0, 0.3, "basically"), _w(0.3, 0.6, "actually"), _w(0.6, 0.9, "beautiful"),
        _w(0.9, 1.9, "slow"),
        _w(1.9, 2.0, "ok"),  # 1 syl / 0.1 s = 10 syl/s → rushed but alone
    ]
    blk = clarity.compute(words, [_seg(0.0, 2.0, "…")], _tracks(x, cfg), cfg.clarity)
    assert abs(blk.rushed_word_fraction - 4 / 5) < 1e-9
    assert len(blk.rushed_runs) == 1
    assert blk.rushed_runs[0].start_s == 0.0 and blk.rushed_runs[0].end_s == 0.9
    assert blk.rushed_runs[0].text == "basically actually beautiful"


def test_zero_duration_word_does_not_divide_by_zero(cfg):
    x = synth.tone(120, 1.0)
    words = [_w(0.5, 0.5, "glitch"), _w(0.5, 0.9, "fine")]
    blk = clarity.compute(words, [_seg(0.0, 1.0, "glitch fine")], _tracks(x, cfg), cfg.clarity)
    assert blk.rushed_word_fraction is not None  # computed over the one word with duration > 0
    assert np.isfinite(blk.rushed_word_fraction)


def test_segment_logprob_stats(cfg):
    x = synth.tone(120, 1.0)
    segs = [_seg(0.0, 0.5, "a", -0.2), _seg(0.5, 1.0, "b", -1.5)]
    blk = clarity.compute([_w(0.0, 0.5, "a"), _w(0.5, 1.0, "b")], segs, _tracks(x, cfg), cfg.clarity)
    assert abs(blk.segment_avg_logprob_mean + 0.85) < 1e-9
    assert abs(blk.low_logprob_segment_fraction - 0.5) < 1e-9


def test_empty_inputs(cfg):
    blk = clarity.compute([], [], _tracks(synth.tone(120, 1.0), cfg), cfg.clarity)
    assert blk.low_conf_word_fraction is None
    assert blk.word_final_drop_fraction is None
    assert blk.rushed_word_fraction is None
    assert blk.segment_avg_logprob_mean is None
    assert blk.low_logprob_segment_fraction is None
    assert blk.low_conf_words == [] and blk.eaten_words == [] and blk.rushed_runs == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clarity.py -v`
Expected: FAIL with `ImportError: cannot import name 'clarity'`

- [ ] **Step 3: Implement clarity.py**

```python
"""Clarity proxies from whisper word boundaries + the intensity contour."""
from __future__ import annotations

import numpy as np

from vocal_coach.analysis.tracks import Tracks
from vocal_coach.config import ClarityConfig
from vocal_coach.transcription.schema import (
    ClarityBlock, EatenWord, LowConfWord, Span, TranscriptSegment, TranscriptWord,
)
from vocal_coach.transcription.syllables import count_syllables


def _fraction(num: int, den: int) -> float | None:
    return float(num / den) if den else None


def _low_confidence(words: list[TranscriptWord], cfg: ClarityConfig) -> tuple[list[LowConfWord], float | None]:
    low = [LowConfWord(start_s=w.start_s, end_s=w.end_s, word=w.word.strip(), probability=w.probability)
           for w in words if w.probability < cfg.low_conf_word_prob]
    return low, _fraction(len(low), len(words))


def _word_final_drops(words: list[TranscriptWord], tracks: Tracks, cfg: ClarityConfig) -> tuple[list[EatenWord], int, float | None]:
    eaten: list[EatenWord] = []
    eligible = 0
    for w in words:
        dur = w.end_s - w.start_s
        if dur < cfg.min_word_duration_s:
            continue
        split = w.end_s - cfg.word_final_tail_fraction * dur
        head = tracks.intensity_between(w.start_s, split)
        tail = tracks.intensity_between(split, w.end_s)
        if len(head) == 0 or len(tail) == 0:
            continue  # timestamps outside the audio, or a window too short for a frame
        eligible += 1
        drop = float(np.median(tail) - np.median(head))
        if drop < -cfg.word_final_drop_db:
            eaten.append(EatenWord(start_s=w.start_s, end_s=w.end_s, word=w.word.strip(), drop_db=drop))
    return eaten, len(eaten), _fraction(len(eaten), eligible)


def _rushed(words: list[TranscriptWord], cfg: ClarityConfig) -> tuple[float | None, list[Span]]:
    flags: list[bool | None] = []  # None = no duration, excluded from the fraction
    for w in words:
        dur = w.end_s - w.start_s
        if dur <= 0:
            flags.append(None)
            continue
        flags.append(count_syllables(w.word) / dur > cfg.rushed_syl_per_sec)
    with_dur = [f for f in flags if f is not None]
    fraction = _fraction(sum(with_dur), len(with_dur))

    runs: list[Span] = []
    run: list[TranscriptWord] = []
    for w, f in zip(words, flags):
        if f:
            run.append(w)
            continue
        if len(run) >= cfg.rushed_run_min_words:
            runs.append(_span(run))
        run = []
    if len(run) >= cfg.rushed_run_min_words:
        runs.append(_span(run))
    return fraction, runs


def _span(run: list[TranscriptWord]) -> Span:
    return Span(start_s=run[0].start_s, end_s=run[-1].end_s, text=" ".join(w.word.strip() for w in run))


def _segment_stats(segments: list[TranscriptSegment], cfg: ClarityConfig) -> tuple[float | None, float | None]:
    if not segments:
        return None, None
    logprobs = np.array([s.avg_logprob for s in segments], dtype=float)
    return float(np.mean(logprobs)), float(np.mean(logprobs < cfg.low_logprob_segment))


def compute(words: list[TranscriptWord], segments: list[TranscriptSegment], tracks: Tracks, cfg: ClarityConfig) -> ClarityBlock:
    low_words, low_fraction = _low_confidence(words, cfg)
    eaten, eaten_count, eaten_fraction = _word_final_drops(words, tracks, cfg)
    rushed_fraction, runs = _rushed(words, cfg)
    logprob_mean, low_logprob_fraction = _segment_stats(segments, cfg)
    return ClarityBlock(
        low_conf_word_fraction=low_fraction,
        low_conf_words=low_words,
        word_final_drop_count=eaten_count,
        word_final_drop_fraction=eaten_fraction,
        eaten_words=eaten,
        rushed_word_fraction=rushed_fraction,
        rushed_runs=runs,
        segment_avg_logprob_mean=logprob_mean,
        low_logprob_segment_fraction=low_logprob_fraction,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_clarity.py -v -W error`
Expected: 8 passed. If `test_eaten_word_detected_by_tail_drop` measures a drop smaller than −6 dB, Praat's 43 ms intensity window smears the attenuation edge; widen the attenuated tail in the fixture to 0.24 s (40 % of the word) rather than loosening the assertion, and say so in the report.

- [ ] **Step 5: Commit**

```bash
git add backend/vocal_coach/transcription/clarity.py backend/tests/test_clarity.py
git commit -m "feat(transcription): clarity proxies (low-confidence, eaten, rushed words)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Whisper transcriber behind a model interface

**Files:**
- Modify: `backend/pyproject.toml` (add `"faster-whisper>=1.0"` to dependencies)
- Modify: `backend/requirements.lock` (regenerate with `pip freeze | grep -v '^-e'` after installing)
- Create: `backend/vocal_coach/transcription/transcriber.py`
- Create: `backend/tests/test_transcriber.py`
- Create: `backend/tests/fake_whisper.py`

**Interfaces:**
- Consumes: `TranscriptionConfig`, `TranscriptWord`, `TranscriptSegment`.
- Produces: `class WhisperLike(Protocol)`: `def transcribe(self, audio: str, **kwargs) -> tuple[Iterable[Any], Any]`; `load_model(cfg: TranscriptionConfig) -> WhisperLike` (real `faster_whisper.WhisperModel(cfg.model_size, device="cpu", compute_type=cfg.compute_type)`); `class RawTranscription(NamedTuple): language: str | None; segments: list[TranscriptSegment]; words: list[TranscriptWord]; text: str`; `transcribe_wav(wav_path: Path, cfg: TranscriptionConfig, model: WhisperLike) -> RawTranscription`.
- Produces (`tests/fake_whisper.py`): `FakeWhisper(segments)` whose `.transcribe(audio, **kwargs)` records `kwargs` in `self.calls` and returns `(iter(segments), SimpleNamespace(language="en"))`; helper `seg(start, end, text, words, avg_logprob=-0.3, no_speech_prob=0.02)` and `word(start, end, word, probability)` building `SimpleNamespace` objects shaped like faster-whisper's `Segment`/`Word`.

- [ ] **Step 1: Install the dependency**

Edit `backend/pyproject.toml` dependencies to add `"faster-whisper>=1.0",`. Run:

```bash
pip install -e ".[dev]" && pip freeze | grep -v '^-e' > requirements.lock
```

Expected: faster-whisper, ctranslate2, tokenizers, huggingface-hub, onnxruntime appear in the lock. Do NOT download a model.

- [ ] **Step 2: Write the fake and the failing test**

`backend/tests/fake_whisper.py`:

```python
"""A stand-in for faster_whisper.WhisperModel that never loads weights."""
from __future__ import annotations

from types import SimpleNamespace


def word(start: float, end: float, text: str, probability: float = 0.9) -> SimpleNamespace:
    return SimpleNamespace(start=start, end=end, word=text, probability=probability)


def seg(start: float, end: float, text: str, words: list[SimpleNamespace] | None,
        avg_logprob: float = -0.3, no_speech_prob: float = 0.02) -> SimpleNamespace:
    return SimpleNamespace(start=start, end=end, text=text, words=words,
                           avg_logprob=avg_logprob, no_speech_prob=no_speech_prob)


class FakeWhisper:
    def __init__(self, segments: list[SimpleNamespace], language: str | None = "en"):
        self._segments = segments
        self._language = language
        self.calls: list[dict] = []

    def transcribe(self, audio: str, **kwargs):
        self.calls.append(kwargs)
        return iter(self._segments), SimpleNamespace(language=self._language)
```

`backend/tests/test_transcriber.py`:

```python
from pathlib import Path

from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.transcription.transcriber import RawTranscription, transcribe_wav


def test_transcribe_converts_segments_and_words(cfg, tmp_path: Path):
    fake = FakeWhisper([
        seg(0.0, 1.2, " Hello there.", [word(0.0, 0.5, " Hello", 0.95), word(0.6, 1.2, " there.", 0.8)]),
        seg(1.5, 2.0, " Um.", [word(1.5, 2.0, " Um.", 0.4)], avg_logprob=-1.2),
    ])
    raw = transcribe_wav(tmp_path / "x.wav", cfg.transcription, fake)
    assert isinstance(raw, RawTranscription)
    assert raw.language == "en"
    assert [s.text for s in raw.segments] == ["Hello there.", "Um."]
    assert raw.segments[1].avg_logprob == -1.2
    assert [w.word for w in raw.words] == ["Hello", "there.", "Um."]
    assert raw.words[2].probability == 0.4
    assert raw.text == "Hello there. Um."


def test_transcribe_passes_fixed_decoding_settings(cfg, tmp_path: Path):
    fake = FakeWhisper([])
    transcribe_wav(tmp_path / "x.wav", cfg.transcription, fake)
    kw = fake.calls[0]
    assert kw["temperature"] == 0.0
    assert kw["beam_size"] == cfg.transcription.beam_size == 5
    assert kw["word_timestamps"] is True
    assert kw["vad_filter"] is False
    assert kw["language"] == "en"


def test_language_none_means_autodetect(cfg, tmp_path: Path):
    tcfg = cfg.transcription.model_copy(update={"language": None})
    fake = FakeWhisper([], language="fr")
    raw = transcribe_wav(tmp_path / "x.wav", tcfg, fake)
    assert fake.calls[0]["language"] is None
    assert raw.language == "fr"


def test_segment_without_words_is_kept(cfg, tmp_path: Path):
    fake = FakeWhisper([seg(0.0, 1.0, " (music)", None)])
    raw = transcribe_wav(tmp_path / "x.wav", cfg.transcription, fake)
    assert len(raw.segments) == 1
    assert raw.words == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_transcriber.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.transcription.transcriber'`

- [ ] **Step 4: Implement transcriber.py**

```python
"""faster-whisper wrapper with fixed decoding settings and an injectable model."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, NamedTuple, Protocol

from vocal_coach.config import TranscriptionConfig
from vocal_coach.transcription.schema import TranscriptSegment, TranscriptWord

DECODE_TEMPERATURE = 0.0  # greedy/beam decoding only: no sampling, for repeatable output
DEVICE = "cpu"  # CPU-only in this environment; GPU selection is a later-plan concern


class WhisperLike(Protocol):
    def transcribe(self, audio: str, **kwargs: Any) -> tuple[Iterable[Any], Any]: ...


class RawTranscription(NamedTuple):
    language: str | None
    segments: list[TranscriptSegment]
    words: list[TranscriptWord]
    text: str


def load_model(cfg: TranscriptionConfig) -> WhisperLike:
    from faster_whisper import WhisperModel  # imported lazily: heavy, and tests never need it

    return WhisperModel(cfg.model_size, device=DEVICE, compute_type=cfg.compute_type)


def transcribe_wav(wav_path: Path, cfg: TranscriptionConfig, model: WhisperLike) -> RawTranscription:
    segments_iter, info = model.transcribe(
        str(wav_path),
        beam_size=cfg.beam_size,
        temperature=DECODE_TEMPERATURE,
        word_timestamps=True,
        vad_filter=False,
        language=cfg.language,
    )
    segments: list[TranscriptSegment] = []
    words: list[TranscriptWord] = []
    for s in segments_iter:
        segments.append(TranscriptSegment(
            start_s=float(s.start), end_s=float(s.end), text=s.text.strip(),
            avg_logprob=float(s.avg_logprob), no_speech_prob=float(s.no_speech_prob),
        ))
        for w in (s.words or []):
            words.append(TranscriptWord(
                start_s=float(w.start), end_s=float(w.end), word=w.word.strip(), probability=float(w.probability),
            ))
    text = " ".join(s.text for s in segments if s.text)
    language = getattr(info, "language", None)
    return RawTranscription(language=language, segments=segments, words=words, text=text)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_transcriber.py -v -W error`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/requirements.lock backend/vocal_coach/transcription/transcriber.py backend/tests/fake_whisper.py backend/tests/test_transcriber.py
git commit -m "feat(transcription): faster-whisper wrapper with injectable model and fixed decoding

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Assemble `transcript.json`, CLI, opt-in real-model test, README

**Files:**
- Create: `backend/vocal_coach/transcription/run.py`
- Create: `backend/tests/test_transcription_run.py`
- Modify: `backend/README.md` (add "Transcription" section)

**Interfaces:**
- Consumes: everything above plus `extract_tracks`, `Tracks`, `to_canonical_json`, `AppConfig`.
- Produces: `build_transcript(raw: RawTranscription, tracks: Tracks, duration_s: float, cfg: AppConfig) -> Transcript`; `transcribe_file(wav_path: Path, cfg: AppConfig, model: WhisperLike | None = None, tracks: Tracks | None = None) -> Transcript` (loads the real model when `model` is None; extracts tracks when `tracks` is None); CLI `python -m vocal_coach.transcription.run <wav> [--out transcript.json] [--config path]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_transcription_run.py`:

```python
import json
import os
from pathlib import Path

import pytest

from tests import synth
from tests.fake_whisper import FakeWhisper, seg, word
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.transcription.run import build_transcript, transcribe_file
from vocal_coach.transcription.schema import TRANSCRIPT_SCHEMA_VERSION, Transcript
from vocal_coach.transcription.transcriber import transcribe_wav


def _audio():
    a = synth.am(synth.vowel(500, 1500, 120, 3.0), 4.0)
    return synth.with_noise_floor(synth.concat(a, synth.silence(0.5), a))


def _fake():
    return FakeWhisper([
        seg(0.0, 3.0, " So basically I was like, you know, fine.", [
            word(0.0, 0.3, " So", 0.9), word(0.3, 0.8, " basically", 0.9), word(0.8, 1.0, " I", 0.9),
            word(1.0, 1.3, " was", 0.9), word(1.3, 1.6, " like,", 0.9), word(1.6, 1.8, " you", 0.9),
            word(1.8, 2.1, " know,", 0.9), word(2.1, 3.0, " fine.", 0.3),
        ]),
        seg(3.5, 6.5, " Um, that is all.", [
            word(3.5, 3.8, " Um,", 0.9), word(3.8, 4.4, " that", 0.9), word(4.4, 4.9, " is", 0.9), word(4.9, 6.5, " all.", 0.9),
        ], avg_logprob=-1.3),
    ])


def test_transcribe_file_end_to_end_with_fake_model(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", _audio())
    t = transcribe_file(wav, cfg, model=_fake())
    assert isinstance(t, Transcript)
    assert t.schema_version == TRANSCRIPT_SCHEMA_VERSION == "1.0"
    assert t.model == "small" and t.language == "en"
    assert t.derived.word_count == 12
    assert abs(t.derived.words_per_min - 12 / (6.5 / 60)) < 1e-6
    assert t.derived.filler_counts == {"um": 1, "uh": 0, "like": 1, "basically": 1, "actually": 0, "you know": 1, "so": 1}
    assert t.derived.filler_total == 5
    assert [w.word for w in t.derived.clarity.low_conf_words] == ["fine."]
    assert t.derived.clarity.segment_avg_logprob_mean is not None
    assert abs(t.derived.clarity.low_logprob_segment_fraction - 0.5) < 1e-9
    data = json.loads(to_canonical_json(t))
    assert set(data) == {"schema_version", "model", "language", "text", "segments", "words", "derived"}
    assert set(data["derived"]) == {"word_count", "words_per_min", "filler_counts", "filler_total", "fillers_per_min", "clarity"}


def test_duration_comes_from_audio_not_last_word(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", _audio())  # 6.5 s of audio
    fake = FakeWhisper([seg(0.0, 1.0, " Hi.", [word(0.0, 1.0, " Hi.", 0.9)])])
    t = transcribe_file(wav, cfg, model=fake)
    assert abs(t.derived.words_per_min - 1 / (6.5 / 60)) < 1e-6


def test_no_speech_gives_empty_transcript_that_serialises(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", synth.with_noise_floor(synth.silence(3.0)))
    t = transcribe_file(wav, cfg, model=FakeWhisper([]))
    assert t.text == "" and t.segments == [] and t.words == []
    assert t.derived.word_count == 0 and t.derived.words_per_min == 0.0
    assert t.derived.filler_total == 0 and t.derived.fillers_per_min == 0.0
    assert t.derived.clarity.low_conf_word_fraction is None
    to_canonical_json(t)


def test_build_transcript_reuses_given_tracks(cfg, tmp_path: Path):
    x = _audio()
    tracks = extract_tracks(synth.to_sound(x), cfg.analysis)
    raw = transcribe_wav(tmp_path / "unused.wav", cfg.transcription, _fake())
    t = build_transcript(raw, tracks, duration_s=tracks.duration_s, cfg=cfg)
    assert t.derived.word_count == 12


@pytest.mark.skipif(os.environ.get("VOCAL_COACH_REAL_WHISPER") != "1", reason="set VOCAL_COACH_REAL_WHISPER=1 to run the real model")
def test_real_whisper_on_synthetic_speech_does_not_crash(cfg, tmp_path: Path):
    wav = synth.write_wav(tmp_path / "s.wav", _audio())
    t = transcribe_file(wav, cfg)
    assert isinstance(t, Transcript)
    to_canonical_json(t)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_transcription_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vocal_coach.transcription.run'`

- [ ] **Step 3: Implement run.py**

```python
"""Assemble transcript.json from whisper output + intensity contour. Also a CLI."""
from __future__ import annotations

import argparse
from pathlib import Path

import parselmouth

from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.tracks import Tracks, extract_tracks
from vocal_coach.config import AppConfig, load_config
from vocal_coach.transcription import clarity
from vocal_coach.transcription.fillers import count_fillers, per_min, words_per_min
from vocal_coach.transcription.schema import TRANSCRIPT_SCHEMA_VERSION, DerivedBlock, Transcript
from vocal_coach.transcription.transcriber import RawTranscription, WhisperLike, load_model, transcribe_wav


def build_transcript(raw: RawTranscription, tracks: Tracks, duration_s: float, cfg: AppConfig) -> Transcript:
    filler_counts = count_fillers(raw.words, cfg.transcription.fillers)
    filler_total = sum(filler_counts.values())
    derived = DerivedBlock(
        word_count=len(raw.words),
        words_per_min=words_per_min(len(raw.words), duration_s),
        filler_counts=filler_counts,
        filler_total=filler_total,
        fillers_per_min=per_min(filler_total, duration_s),
        clarity=clarity.compute(raw.words, raw.segments, tracks, cfg.clarity),
    )
    return Transcript(
        schema_version=TRANSCRIPT_SCHEMA_VERSION,
        model=cfg.transcription.model_size,
        language=raw.language,
        text=raw.text,
        segments=raw.segments,
        words=raw.words,
        derived=derived,
    )


def transcribe_file(
    wav_path: Path,
    cfg: AppConfig,
    model: WhisperLike | None = None,
    tracks: Tracks | None = None,
) -> Transcript:
    if tracks is None:
        tracks = extract_tracks(parselmouth.Sound(str(wav_path)), cfg.analysis)
    if model is None:
        model = load_model(cfg.transcription)
    raw = transcribe_wav(wav_path, cfg.transcription, model)
    return build_transcript(raw, tracks, duration_s=tracks.duration_s, cfg=cfg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe a 16 kHz WAV and write transcript JSON.")
    parser.add_argument("wav", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="Output path (default: stdout)")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    text = to_canonical_json(transcribe_file(args.wav, cfg))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole suite**

Run: `pytest -v -W error`
Expected: all pass; the real-whisper test is reported as skipped.

- [ ] **Step 5: README**

Append to `backend/README.md`:

````markdown
## Transcription (Plan 2)

`transcript.json` = faster-whisper (CPU, `int8`, model size from `config.yaml → transcription.model_size`, beam 5, temperature 0, word timestamps) + filler counts + clarity proxies (low-confidence, half-eaten and rushed words). It is kept separate from `metrics.json` because whisper output is only deterministic for a fixed build and hardware.

```bash
python -m vocal_coach.transcription.run data/work/recording.wav --out data/transcript.json
```

The first run downloads the model (~460 MB for `small`) into the Hugging Face cache. Tests use a fake model; run the real one with `VOCAL_COACH_REAL_WHISPER=1 pytest tests/test_transcription_run.py`.

### Pinned dependencies — what bumps `ANALYSER_VERSION`

Only changes to packages that affect `metrics.json` numbers (praat-parselmouth, numpy, scipy, and the ffmpeg binary) require an `ANALYSER_VERSION` bump. Transcription packages (faster-whisper, ctranslate2, tokenizers) are recorded in `transcript.json → model` and do not touch `metrics.json`.
````

Update the earlier "Pinned dependencies" paragraph (from Plan 1) to point at this section rather than saying "any change".

- [ ] **Step 6: Commit**

```bash
git add backend/vocal_coach/transcription/run.py backend/tests/test_transcription_run.py backend/README.md
git commit -m "feat(transcription): transcript.json assembly, CLI, and README

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage (§7, §7.1):** transcriber settings → Task 5; fillers + WPM → Task 3; syllables → Task 2; clarity metrics (all nine fields) → Task 4; `transcript.json` shape → Tasks 2 and 6; config sections → Task 1. §16 `test_fillers`, `test_clarity` present. Later plans consume `transcribe_file(wav, cfg, model=None, tracks=None)` and `Transcript`.
- **Deviation, deliberate:** probabilities/logprobs/fractions serialised at 6 decimals (spec's rule says "ratios" at 6 — these are ratios); `SIX_DECIMAL_FIELDS` extended in Task 1 without touching any metrics key, so Plan 1's determinism test is unaffected.
- **Type consistency:** `TranscriptWord`/`TranscriptSegment` defined in Task 2, consumed by 3, 4, 5, 6 with the same field names; `RawTranscription` (Task 5) consumed by Task 6; `ClarityConfig`/`TranscriptionConfig` (Task 1) consumed by 4, 5, 6; `count_syllables`/`normalise_token` (Task 2) consumed by 3 and 4.
- **Review Focus pins:** 1 → `test_zero_duration_word_does_not_divide_by_zero` (Task 4); 2 → `test_word_past_audio_end_is_skipped_not_raised` (Task 4); 3 → `test_no_speech_gives_empty_transcript_that_serialises` (Task 6); 4 → `test_count_syllables` "hmm"/"2024"/"..." (Task 2); 5 → `test_multiword_filler_across_segment_boundary_and_case` (Task 3).
- **Known heuristic limits, documented in tests:** syllable counter undercounts mid-word "ua" hiatus ("actually" → 3). Filler "so"/"like" are counted naively per spec.
