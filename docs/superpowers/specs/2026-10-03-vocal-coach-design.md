# Vocal Coach — Design Spec

Date: 2026-10-03
Status: approved for planning

See §20 for amendments made during implementation.

## 1. Purpose

A multi-user web app that pulls a speaker's audio or video recordings from their Google Drive (or local upload), measures the voice with pure signal analysis, and turns those measurements into coaching feedback via an LLM. React frontend, FastAPI backend, Keycloak for login, Postgres for storage.

Target user: someone rehearsing spoken delivery (e.g. a sales pitch) who records themselves repeatedly and wants to know what changed and what to fix next.

Success criteria:

- Same input file, same config → byte-identical `metrics.json`, every run, every machine.
- The app is fully usable with the LLM path switched off.
- Every number in LLM output traces to the metrics JSON or comparison deltas; any that does not is flagged in the UI.
- Two or more recordings can be compared side by side with direction-aware improvement markers.
- Each user sees only their own recordings, analyses and Drive connection.

## 2. Core principle: two paths

1. **Deterministic path.** Signal analysis only. Fixed parameters from `config.yaml`. No randomness, no model inference. Source of truth.
2. **LLM path.** Consumes `metrics.json`, `transcript.json`, comparison deltas and speaker context. Interprets; never computes or invents numbers.

Transcription sits between them: faster-whisper with temperature 0 and fixed beam is *deterministic-ish* (stable for a given build, not guaranteed identical across CPU/GPU/thread counts). It is kept **out of `metrics.json`** and lives in a separate `transcript.json`. The determinism test covers `metrics.json` only.

## 3. Architecture

```
browser (React, Vite, TS)
   │ OIDC Authorization Code + PKCE ──► Keycloak
   │ Bearer JWT on every /api call
   ▼
FastAPI backend ──► Postgres (app DB)
   ├─ auth/          JWT verification via Keycloak JWKS, user upsert
   ├─ api/           routers
   ├─ jobs/          thread-pool runner, jobs table, SSE
   ├─ drive/         per-user Google OAuth web flow, encrypted refresh tokens, download cache
   ├─ analysis/      deterministic metrics
   ├─ transcription/ faster-whisper, fillers, clarity
   ├─ storage/       SQLAlchemy models, comparison
   ├─ llm/           provider registry, coach, number check
   └─ pipeline.py    download → extract → analyse → transcribe → coach
   ▼
ffmpeg, praat-parselmouth, faster-whisper, LLM endpoint (OpenAI-compatible or Anthropic)
```

### 3.1 Repository layout

```
voice-analysis/
├── docker-compose.yml
├── .env.example
├── README.md
├── keycloak/
│   └── realm-export.json          # realm vocal-coach, client vocal-coach-web, role user
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   ├── config.yaml                # analysis params, thresholds, direction rules, llm, transcription
│   ├── Dockerfile                 # python 3.11 + ffmpeg
│   ├── vocal_coach/
│   │   ├── main.py                # FastAPI app factory, routers, startup checks
│   │   ├── settings.py            # env vars (pydantic-settings)
│   │   ├── config.py              # load config.yaml, validate, config_hash
│   │   ├── pipeline.py
│   │   ├── auth/
│   │   │   ├── jwt.py             # JWKS fetch/cache, token verify
│   │   │   └── deps.py            # current_user dependency
│   │   ├── api/
│   │   │   ├── me.py
│   │   │   ├── drive.py
│   │   │   ├── analyses.py
│   │   │   ├── jobs.py
│   │   │   ├── comparisons.py
│   │   │   ├── llm.py
│   │   │   └── config_public.py
│   │   ├── jobs/
│   │   │   ├── runner.py          # ThreadPoolExecutor, job lifecycle
│   │   │   └── events.py          # SSE generator
│   │   ├── drive/
│   │   │   ├── oauth.py           # consent URL, callback exchange, token crypto
│   │   │   ├── client.py          # list folder, download
│   │   │   └── cache.py
│   │   ├── analysis/
│   │   │   ├── audio.py
│   │   │   ├── pitch.py
│   │   │   ├── phrasing.py
│   │   │   ├── pace.py
│   │   │   ├── intonation.py
│   │   │   ├── energy.py
│   │   │   ├── voice_quality.py
│   │   │   ├── articulation.py
│   │   │   ├── timeline.py
│   │   │   ├── schema.py          # pydantic MetricsReport
│   │   │   └── analyser.py        # ANALYSER_VERSION
│   │   ├── transcription/
│   │   │   ├── transcriber.py
│   │   │   ├── fillers.py
│   │   │   ├── syllables.py
│   │   │   ├── clarity.py
│   │   │   └── schema.py          # pydantic Transcript
│   │   ├── storage/
│   │   │   ├── models.py          # SQLAlchemy 2 models
│   │   │   ├── db.py              # engine, session
│   │   │   ├── repo.py            # user-scoped queries
│   │   │   └── comparison.py
│   │   └── llm/
│   │       ├── base.py
│   │       ├── registry.py
│   │       ├── openai_compatible_provider.py
│   │       ├── anthropic_provider.py
│   │       ├── schema.py          # pydantic CoachingOutput
│   │       ├── coach.py
│   │       ├── number_check.py
│   │       └── prompts/coach.md
│   └── tests/
│       ├── conftest.py            # synthetic audio fixtures, test DB, test JWT signer
│       ├── test_audio.py
│       ├── test_pitch.py
│       ├── test_phrasing.py
│       ├── test_pace.py
│       ├── test_intonation.py
│       ├── test_energy.py
│       ├── test_articulation.py
│       ├── test_clarity.py
│       ├── test_fillers.py
│       ├── test_determinism.py
│       ├── test_comparison.py
│       ├── test_repo.py
│       ├── test_number_check.py
│       ├── test_coach.py
│       ├── test_llm_contract.py
│       ├── test_openai_compatible_provider.py
│       ├── test_anthropic_provider.py
│       ├── test_auth.py
│       ├── test_jobs.py
│       ├── test_api_analyses.py
│       ├── test_drive_oauth.py
│       └── test_drive_cache.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── Dockerfile                 # build → nginx, proxies /api
    ├── nginx.conf
    └── src/
        ├── main.tsx
        ├── auth/                  # oidc-client-ts config, AuthProvider, RequireAuth
        ├── api/
        │   ├── client.ts          # fetch wrapper, bearer injection
        │   ├── types.ts           # generated from OpenAPI
        │   └── hooks.ts           # TanStack Query hooks
        ├── pages/
        │   ├── LoginPage.tsx
        │   ├── LibraryPage.tsx
        │   ├── AnalysisPage.tsx
        │   ├── ComparePage.tsx
        │   └── SettingsPage.tsx
        ├── components/
        │   ├── analyse/           # AnalyseDrawer, DriveBrowser, UploadDropzone, JobProgress
        │   ├── analysis/          # SummaryCards, TimelineCharts, CoachingPanel, TranscriptView, RawJson
        │   └── compare/           # ComparisonTable, TrendCharts
        └── test/                  # Vitest + RTL + MSW
```

Each `analysis/*.py` module exposes one public function `compute(sound, cfg, **deps) -> <pydantic block>`. Modules do not import each other; `analyser.py` passes the phrase list and peak list to `intonation`, `energy`, `articulation`.

## 4. Authentication and authorisation

- **Keycloak** realm `vocal-coach`, imported from `keycloak/realm-export.json` on container start. Public client `vocal-coach-web`: standard flow, PKCE S256, redirect URIs = frontend origin. Default role `user`. Signup policy, email verification, password rules, social IdPs are Keycloak realm settings, not app code.
- **Frontend**: `oidc-client-ts` + `react-oidc-context`. Authorization Code + PKCE, silent renew via refresh token. Unauthenticated users see `/login` only.
- **Backend**: `current_user` dependency verifies RS256 JWT: signature against Keycloak JWKS (cached, refreshed on unknown `kid`), `iss == KEYCLOAK_ISSUER`, `aud` contains `KEYCLOAK_AUDIENCE`, `exp`. Extracts `sub`, `email`, `preferred_username`; upserts `users` row on first sight. Invalid or missing token → 401.
- **Authorisation**: strict per-user. Every repository query takes `user_id`. Accessing another user's analysis or job by id → 404 (not 403, to avoid id enumeration). No admin role in v1.

## 5. Input: Google Drive (per user) and upload

- **Linking** is separate from login. Server-wide Google OAuth web client (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`), scope `https://www.googleapis.com/auth/drive.readonly`, `access_type=offline`, `prompt=consent`.
  - `GET /api/drive/connect` → consent URL with `state` = signed `(user_id, nonce, exp)` (itsdangerous, `SECRET_KEY`).
  - `GET /api/drive/callback?code&state` → verifies state, exchanges code, stores refresh token encrypted with Fernet (`DRIVE_TOKEN_KEY`) in `drive_connections`, redirects to frontend `/settings?drive=connected`.
  - `DELETE /api/drive/connect` → revokes at Google, deletes row.
- **Listing**: `GET /api/drive/files?folder_id=` lists files whose extension ∈ `{m4a, mp3, wav, mov, mp4}` → `name, id, modifiedTime, size, mimeType`. Default `folder_id` = root. Access token obtained from refresh token per request, never stored.
- **Cache**: `DATA_DIR/cache/<user_id>/<file_id>__<modifiedTime-sanitised>.<ext>`. Cache hit = no download. Derived 16 kHz WAV stored beside it.
- **Upload**: `POST /api/analyses` multipart, same extensions, size limit `MAX_UPLOAD_MB` (default 500). Uploaded files have `drive_file_id = null`, stored under `DATA_DIR/uploads/<user_id>/<sha256>.<ext>`.
- Service-account mode is dropped: meaningless for per-user Drive.

## 6. Deterministic pipeline

### 6.1 Audio extraction (`analysis/audio.py`)

`ffmpeg -i <in> -vn -ac 1 -ar 16000 -sample_fmt s16 -f wav <out>` via subprocess. `content_sha256` is computed over the resulting WAV so container metadata cannot change it. Startup check fails loudly if ffmpeg is missing.

### 6.2 Fixed parameters (`backend/config.yaml`)

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
  min_duration_s: 2.0
articulation:
  hf_band_hz: [2000, 8000]
  lf_band_hz: [0, 1000]
  modulation_band_hz: [2, 10]
  weak_peak_prominence_db: 4
  formant_max_hz: 5500
  formant_trim_pct: 5
```

`config_hash = "sha256:" + sha256(canonical JSON of analysis + articulation sections)`. Any change to a number that affects metrics changes the hash.

### 6.3 Metrics

**recording_quality** (in `analyser.py`) — `noise_floor_db` = p5 of intensity; `snr_estimate_db` = median speaking intensity − noise floor; `low_confidence` if noise floor > `low_confidence_noise_floor_db` or SNR < `low_confidence_snr_db`; `reasons[]` lists which fired.
Intensity is clamped at 0 dB before any metric; Praat reports −300 dB for digital silence. A noise-gated recording therefore reports `noise_floor_db = 0.0`.

**pitch.py** — Praat `To Pitch (ac)` with time step, floor, ceiling. Voiced frames only.
- `f0_median_hz`, `f0_p10_hz`, `f0_p90_hz`, `f0_range_st = 12·log2(p90/p10)`
- `voiced_fraction`
- `creak_fraction_below_100hz` = voiced frames with F0 < `creak_threshold_hz` ÷ voiced frames
- `opening_f0_median_hz` over first `opening_window_s`; `opening_vs_overall_st`

**phrasing.py** — Praat `To TextGrid (silences)`. Sounding intervals = phrases; silences between phrases = pauses (leading/trailing silence excluded).
- `phrase_count`, `speaking_time_s`, `mean_phrase_length_s`
- `pause_count`, `pauses_per_min` (per minute of total duration), `mean_pause_length_s`
- `long_pause_count_ge_1s`, `long_pauses[] {start_s, end_s, duration_s}`

**pace.py** — Intensity contour (`To Intensity`, min pitch = floor). Peaks via `scipy.signal.find_peaks(prominence=syllable_peak_prominence_db, wlen=0.4 s)` restricted to voiced frames; the 0.4 s window judges each syllable against its own neighbourhood, not distant silence.
- `syllable_count_est`, `syllables_per_sec_overall` (÷ total duration), `articulation_rate_syl_per_sec` (÷ speaking time)

**intonation.py** — Per phrase: median F0 of last `intonation_tail_s` vs phrase median, semitones. `up` > +threshold, `down` < −threshold, else `flat`. Phrases with no voiced tail → `unclassified_count`.
- `up_count`, `down_count`, `flat_count`, `unclassified_count`, `flat_pct` (of classified)
- `per_phrase[] {start_s, end_s, end_delta_st, class}`

**energy.py** —
- `final_15s_median_db` = median speaking intensity over the last `energy_window_s` seconds of speech, anchored at the end of the last phrase.
- `body_median_db` = median speaking intensity before that final window; `final_vs_body_db` = final − body
- `per_phrase_end_drop_db[]` = median of last `phrase_end_tail_s` − phrase median; `trailing_off_count` = drops < −`trailing_off_drop_db`

**voice_quality.py** — `To Harmonicity (cc)`, `To PointProcess (periodic, cc)`, jitter (local), shimmer (local).
- `hnr_db`, `jitter_local`, `shimmer_local`, `low_confidence` = recording_quality.low_confidence

**articulation.py** — proxies for mumbling / vowel reduction. Speaking frames only.
- `hf_energy_ratio_db` = median over frames of 10·log10(E[hf_band] / E[lf_band]), STFT 25 ms Hann, 10 ms hop
- `spectral_tilt_db_per_oct` = (mean dB power in `hf_band_hz` − mean dB power in `lf_band_hz`) ÷ log2(midpoint(hf)/midpoint(lf)), Welch PSD over speaking samples. Partly redundant with `hf_energy_ratio_db`; kept as a per-octave normalised view.
- `modulation_depth` = RMS of intensity contour band-passed to `modulation_band_hz` ÷ mean intensity (linear)
- `syllable_peak_prominence_mean_db`, `syllable_peak_prominence_p25_db`, `weak_peak_fraction` (prominence < `weak_peak_prominence_db`)
- `vowel_space`: `To Formant (burg)` (0.01 s, 5 formants, `formant_max_hz`), F1/F2 at voiced frames, trimmed to [p5, p95] per axis → `f1_sd_hz`, `f2_sd_hz`, `vowel_space_area_hz2` (convex hull), `vowel_dispersion_st` (mean semitone distance from centroid)
- `low_confidence` = recording_quality.low_confidence OR `f0_median_hz` > `low_confidence_f0_hz`

**timeline.py** — fixed `energy_window_s` windows from 0. Per window `f0_median_hz`, `f0_sd_st` (SD of 12·log2(F0 / window median)), `intensity_median_db`. No voiced frames → F0 fields `null`.

### 6.4 `metrics.json` schema (`MetricsReport`, `schema_version "1.0"`)

```json
{
  "schema_version": "1.0",
  "analyser_version": "0.1.0",
  "config_hash": "sha256:…",
  "source": {
    "file_name": "…", "drive_file_id": "… | null", "drive_modified_time": "… | null",
    "content_sha256": "…", "duration_s": 0.0, "original_channels": 1, "original_sample_rate": 44100
  },
  "recording_quality": { "noise_floor_db": 0.0, "snr_estimate_db": 0.0, "low_confidence": false, "reasons": [] },
  "pitch": {
    "f0_median_hz": 0.0, "f0_p10_hz": 0.0, "f0_p90_hz": 0.0, "f0_range_st": 0.0,
    "voiced_fraction": 0.0, "creak_fraction_below_100hz": 0.0,
    "opening_f0_median_hz": 0.0, "opening_vs_overall_st": 0.0
  },
  "phrasing": {
    "phrase_count": 0, "speaking_time_s": 0.0, "mean_phrase_length_s": 0.0,
    "pause_count": 0, "pauses_per_min": 0.0, "mean_pause_length_s": 0.0,
    "long_pause_count_ge_1s": 0, "long_pauses": [{ "start_s": 0.0, "end_s": 0.0, "duration_s": 0.0 }]
  },
  "pace": { "syllable_count_est": 0, "syllables_per_sec_overall": 0.0, "articulation_rate_syl_per_sec": 0.0 },
  "intonation": {
    "up_count": 0, "down_count": 0, "flat_count": 0, "unclassified_count": 0, "flat_pct": 0.0,
    "per_phrase": [{ "start_s": 0.0, "end_s": 0.0, "end_delta_st": 0.0, "class": "up|down|flat" }]
  },
  "energy": {
    "body_median_db": 0.0, "final_15s_median_db": 0.0, "final_vs_body_db": 0.0,
    "trailing_off_count": 0, "per_phrase_end_drop_db": [0.0]
  },
  "voice_quality": { "hnr_db": 0.0, "jitter_local": 0.0, "shimmer_local": 0.0, "low_confidence": false },
  "articulation": {
    "hf_energy_ratio_db": 0.0, "spectral_tilt_db_per_oct": 0.0, "modulation_depth": 0.0,
    "syllable_peak_prominence_mean_db": 0.0, "syllable_peak_prominence_p25_db": 0.0, "weak_peak_fraction": 0.0,
    "vowel_space": { "f1_sd_hz": 0.0, "f2_sd_hz": 0.0, "vowel_space_area_hz2": 0.0, "vowel_dispersion_st": 0.0 },
    "low_confidence": false
  },
  "timeline": {
    "window_s": 15,
    "windows": [{ "start_s": 0.0, "end_s": 15.0, "f0_median_hz": 0.0, "f0_sd_st": 0.0, "intensity_median_db": 0.0 }]
  }
}
```

Serialisation: floats rounded to 4 decimals (Hz, dB, s, st) or 6 decimals (ratios, jitter, shimmer); `json.dumps(sort_keys=True, separators=(",", ":"))`. Thresholds are not in the JSON; `config_hash` covers them.

## 7. Transcription

- `transcriber.py`: faster-whisper on the decoded 16 kHz samples (not the file path), `temperature 0`, `beam_size` from config, `word_timestamps true`, `vad_filter false`, `condition_on_previous_text false`; model loaded once per process behind a lock. `model_size` (default `small`), `compute_type` (default `int8`), `language` (default `en`). Returns segments (`avg_logprob`, `no_speech_prob`) and words (`probability`). Words from segments with `no_speech_prob > transcription.no_speech_exclude_prob` (default 0.6) stay in `segments`/`words` but are excluded from `derived`.
- `fillers.py`: filler list from config, case-insensitive on normalised tokens; multi-word fillers matched on adjacent words. `words_per_min` = words ÷ total minutes.
- `syllables.py`: deterministic English vowel-cluster syllable estimate, no external dictionary.
- `clarity.py`: takes words + WAV + config.

```yaml
transcription:
  model_size: small
  compute_type: int8
  beam_size: 5
  language: en
  no_speech_exclude_prob: 0.6
  fillers: [um, uh, like, basically, actually, "you know", so]
clarity:
  low_conf_word_prob: 0.5
  word_final_drop_db: 6
  word_final_tail_fraction: 0.3
  min_word_duration_s: 0.25
  rushed_syl_per_sec: 7
  rushed_run_min_words: 3
  low_logprob_segment: -1.0
```

Clarity metrics:
- `low_conf_word_fraction`, `low_conf_words[] {start_s, end_s, word, probability}`
- `word_final_drop_count`, `word_final_drop_fraction` (of words ≥ `min_word_duration_s`), `eaten_words[] {start_s, end_s, word, drop_db}` — intensity median of last `word_final_tail_fraction` of the word vs the rest
- `rushed_word_fraction`, `rushed_runs[] {start_s, end_s, text}` — syl/s > `rushed_syl_per_sec`; run = ≥ `rushed_run_min_words` consecutive
- `segment_avg_logprob_mean`, `low_logprob_segment_fraction`

### 7.1 `transcript.json` schema (`Transcript`, `schema_version "1.0"`)

```json
{
  "schema_version": "1.0",
  "model": "small", "language": "en", "text": "…",
  "segments": [{ "start_s": 0.0, "end_s": 0.0, "text": "…", "avg_logprob": 0.0, "no_speech_prob": 0.0 }],
  "words": [{ "start_s": 0.0, "end_s": 0.0, "word": "…", "probability": 0.0 }],
  "derived": {
    "word_count": 0, "words_per_min": 0.0,
    "filler_counts": { "um": 0 }, "filler_total": 0, "fillers_per_min": 0.0,
    "clarity": {
      "low_conf_word_fraction": 0.0, "low_conf_words": [],
      "word_final_drop_count": 0, "word_final_drop_fraction": 0.0, "eaten_words": [],
      "rushed_word_fraction": 0.0, "rushed_runs": [],
      "segment_avg_logprob_mean": 0.0, "low_logprob_segment_fraction": 0.0
    }
  }
}
```

## 8. Storage (Postgres, SQLAlchemy 2, Alembic)

```
users             id uuid pk, keycloak_sub text unique, email text, username text, created_at
drive_connections user_id uuid pk fk, encrypted_refresh_token bytea, google_email text, connected_at
analyses          id uuid pk, user_id fk, file_name, drive_file_id null, content_sha256 (extracted-WAV hash),
                  source_sha256 null (uploaded-bytes hash; names the stored upload),
                  recorded_at (Drive modifiedTime or upload time), analysed_at,
                  analyser_version, config_hash, metrics_json jsonb, transcript_json jsonb null,
                  speaker_context text null, coaching_json jsonb null, coaching_warnings jsonb null
                  unique (user_id, content_sha256, config_hash, analyser_version)
                  index (user_id, recorded_at)
jobs              id uuid pk, user_id fk, status (queued|running|done|failed), stage text,
                  progress_pct int, error text null, analysis_id fk null, created_at, updated_at,
                  file_name null, source_sha256 null, recorded_at null (kept for retry)
```

Re-analysing the same file with the same config and analyser version for the same user returns the stored analysis (a new analyser version yields a new row; the old one is kept) (job completes immediately, coaching re-run only if context or model changed).

## 9. Comparison

`storage/comparison.py` takes N of the user's analyses ordered by `recorded_at`. For each dotted metric path in `comparison.directions` it computes delta between consecutive recordings and vs the first.

```yaml
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
```

Per metric: `{path, values[], delta, arrow (↑ ↓ →), verdict (improved | worsened | neutral | unchanged)}`. `unchanged` when |delta| < `min_meaningful_change_pct` % of the earlier value. Differing `config_hash` across recordings → compared, but response carries `config_mismatch: true` and the UI shows a banner. Trend series returned for every path in `directions`.

`delta`/verdict use the first and last available values; `partial: true` marks rows with gaps; `analyser_version_mismatch` reported alongside `config_mismatch`.

## 10. Jobs and progress

- `jobs/runner.py`: `ThreadPoolExecutor(max_workers=JOB_WORKERS, default 2)`. `POST /api/analyses` inserts `queued` job, submits `pipeline.run(job_id)`. Pipeline callback writes `stage`, `progress_pct` to the job row at each transition: `download → extract → analyse → transcribe → coach → done`.
- `GET /api/jobs/{id}/events`: SSE. Polls the job row every 500 ms, emits `stage`, `progress`, `done {analysis_id}`, `error {message}`; closes on done/failed. Client falls back to `GET /api/jobs/{id}` polling if SSE drops. A stream open longer than an hour ends with `timeout {message}` (not an error: the job may still be running; the client switches to polling). Each poll uses its own short session off the event loop; an open stream holds no database connection.
- `GET /api/jobs?status=&limit=`: the user's jobs, newest first (`status` one of `queued|running|done|failed`), each with `file_name` and `created_at`.
- `POST /api/jobs/{id}/retry`: re-runs a finished job's upload as a new job → 202 `{job_id}`; 404 foreign/missing, 409 not finished, 410 the upload is no longer stored.
- Uploads are stored once per user as `DATA_DIR/uploads/<user_id>/<source_sha256>.<ext>`; jobs and analyses record `source_sha256` (the uploaded bytes' hash), distinct from `content_sha256` (the extracted WAV's hash, the dedupe key).
- A worker process that dies marks its job `failed` (`worker crashed: …`) and the pool is rebuilt; if it cannot be rebuilt the upload answers 503 and the job is `failed / job runner unavailable`.
- On backend startup, jobs in `queued|running` are marked `failed` with error `"server restarted"`.
- One job per file; multi-select creates N jobs.

## 11. LLM path

### 11.1 Interface and registry

```python
class LLMProvider(ABC):
    name: str
    def __init__(self, cfg: LLMConfig): ...
    @abstractmethod
    def generate_coaching(self, system_prompt: str, user_payload: dict, schema: dict) -> dict: ...
    def list_models(self) -> list[str]: return []
```

`registry.py`: `@register("name")` populates a dict; `get_provider(name, cfg)`; `names()`. API and pipeline only touch the registry. Adding a provider = one new file with the decorator.

### 11.2 Providers

- **openai_compatible_provider.py** — `openai` SDK at `llm.base_url`, `llm.model`, key from `OPENAI_COMPAT_API_KEY` (optional). Tries `response_format={"type":"json_schema","json_schema":{…,"strict":true}}`; on 4xx retries with `{"type":"json_object"}` plus schema text in the system prompt. `temperature 0`, `seed llm.seed`. `list_models()` = `GET {base_url}/models`.
- **anthropic_provider.py** — `anthropic` SDK, key from `ANTHROPIC_API_KEY`, model from `llm.model`. Forced single tool whose input schema is the output schema. `temperature 0`. No seed (unsupported).

No model name hard-coded. Settings are server-wide:

```yaml
llm:
  enabled: true
  provider: openai_compatible      # openai_compatible | anthropic
  base_url: http://localhost:11434/v1
  model: ""
  allowed_models: []               # empty = expose whatever list_models returns
  seed: 42
  timeout_s: 120
```

Users choose a model from `GET /api/llm/models` and toggle coaching per analysis. Users cannot set base URL or keys.

### 11.3 Payload, output, validation (`llm/coach.py`)

Payload: `{metrics, transcript_text, transcript_derived, comparison | null, speaker_context}`. `per_phrase`, `per_phrase_end_drop_db`, `words` are dropped; `long_pauses`, `eaten_words`, `rushed_runs`, `low_conf_words` kept, capped at 20 each. `comparison` = deltas vs the user's previous analysis when one exists.

Output (`CoachingOutput`):

```json
{ "what_improved": ["…"], "what_is_lacking": ["…"], "next_steps": ["…"], "marked_up_example": "…" }
```

Flow: call → validate. On failure retry once with the validation error under `previous_error`. On second failure store `coaching_json = null`, `coaching_warnings = ["invalid model output"]`; the analysis still completes. Provider exceptions handled the same way with the message.

`marked_up_example`: 2–3 real transcript sentences, words unchanged, `//` = 1–1.5 s pause, CAPS = stressed word, `↘` = falling finish. Post-check: de-marked, lowercased, punctuation-stripped text must appear as a contiguous word sequence in the transcript; otherwise a warning.

### 11.4 System prompt (`llm/prompts/coach.md`)

Cite metrics by name and value; never invent or re-round numbers; state when a metric is `low_confidence`; articulation and clarity metrics are indirect proxies, phrase as "suggests" and pair with `eaten_words` / `rushed_runs` examples; focus on the 1–3 highest-impact changes; respond only with JSON matching the schema.

### 11.5 Number post-check (`llm/number_check.py`)

Extract numeric tokens from the four output fields (ignoring `//`). Allowed set = every numeric leaf in `metrics`, `transcript.derived`, `comparison` as sent, each at 0/1/2 decimals. Unmatched numbers → `coaching_warnings[]`, rendered in the Coaching panel.

## 12. API (`/api`, Bearer required)

| Method | Path | Purpose |
|---|---|---|
| GET | `/me` | profile, `drive_connected`, `llm_enabled`, `llm_provider` |
| GET | `/drive/connect` | Google consent URL |
| GET | `/drive/callback` | OAuth callback (redirects to frontend) |
| DELETE | `/drive/connect` | unlink |
| GET | `/drive/files?folder_id=` | list audio/video files |
| POST | `/analyses` | JSON `{source:"drive", file_ids[], speaker_context, llm:{enabled, model}}` or multipart upload with same fields → `{job_ids[]}` |
| GET | `/jobs?status=&limit=` | the user's jobs, newest first, with `file_name`, `created_at` |
| GET | `/jobs/{id}` | status |
| POST | `/jobs/{id}/retry` | re-run a finished job's upload → 202 `{job_id}`; 409 if not finished, 410 if the upload is gone |
| GET | `/jobs/{id}/events` | SSE (`stage`, `progress`, `done`, `error`, `timeout`) |
| GET | `/analyses` | list (id, file_name, recorded_at, key summary metrics, has_coaching); returns summaries (no blobs), paginated |
| GET | `/analyses/{id}` | full record |
| GET | `/analyses/{id}/raw/{kind}` | download `metrics` / `transcript` / `coaching` JSON as an attachment; 404 when absent |
| DELETE | `/analyses/{id}` | delete analysis and its upload once nothing else references it |
| POST | `/analyses/{id}/coach` | re-run LLM with new `{speaker_context, model}` |
| GET | `/comparisons?ids=a,b,c` | deltas table + trend series |
| GET | `/llm/models` | `{provider, models[]}` or `{enabled:false}` |
| GET | `/config/public` | thresholds + direction rules for UI legends |

OpenAPI → `openapi-typescript` → `frontend/src/api/types.ts` (checked in, regenerated by script).

## 13. Frontend

Stack: Vite, React 18, TypeScript, React Router, TanStack Query, `oidc-client-ts` + `react-oidc-context`, Recharts, Tailwind. Tests: Vitest, React Testing Library, MSW.

Pages:
- `/login` — Keycloak redirect button; auto-redirect if a return URL is set.
- `/` **Library** — table of analyses (name, date, key metrics, coaching badge), Compare selection checkboxes, Analyse button → **AnalyseDrawer**: source tabs (Drive browser: folder id input, file list, multi-select; or UploadDropzone), speaker context, LLM toggle + model select. Submit → **JobProgress** list with live SSE stages per file; done rows link to the analysis.
- `/analyses/:id` **Analysis** — tabs: Summary (metric cards incl. low-confidence badges), Timeline (F0 median, F0 SD, intensity per window), Coaching (sections, warnings list, marked-up example monospace, "re-run coaching" form; unavailable state when off/failed), Transcript (pauses ≥ 1 s as `[pause 1.4s]`, fillers / eaten words / low-confidence words highlighted with legend), Raw JSON (metrics, transcript, coaching, download buttons).
- `/compare?ids=` **Compare** — side-by-side table with arrows and verdict colours, config-mismatch banner, trend charts.
- `/settings` — Drive connect/disconnect with connected Google email, account info, sign out.

## 14. Deployment

`docker-compose.yml` services:
- `postgres` — databases `keycloak` and `vocal_coach`, volume.
- `keycloak` — `start --import-realm`, realm JSON mounted, admin creds from `.env`.
- `backend` — image with ffmpeg; runs Alembic migrations then uvicorn; volumes `DATA_DIR` (uploads, cache) and whisper model cache.
- `frontend` — nginx serving the Vite build, proxying `/api` to backend.

Dev mode: compose up `postgres keycloak` only; `uvicorn --reload` and `vite dev` locally with Vite proxy for `/api`.

`.env.example`: `POSTGRES_*`, `KEYCLOAK_ADMIN*`, `KEYCLOAK_ISSUER`, `KEYCLOAK_AUDIENCE`, `SECRET_KEY`, `DRIVE_TOKEN_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_ORIGIN`, `DATA_DIR`, `JOB_WORKERS`, `MAX_UPLOAD_MB`, `OPENAI_COMPAT_API_KEY`, `ANTHROPIC_API_KEY`.

## 15. Error handling

- Missing ffmpeg → backend refuses to start with a clear message.
- Invalid/expired JWT → 401; frontend triggers silent renew then re-login.
- Drive not connected → `/drive/files` returns 409 `drive_not_connected`; UI shows connect prompt. Google token revoked → same, connection row deleted.
- Upload too large / wrong type → 413 / 415.
- Audio shorter than `min_duration_s` → report with `recording_quality.reasons = ["too_short"]`, all metric fields null; no voiced frames → `["no_voiced_speech"]`. UI shows a warning instead of cards.
- faster-whisper failure → `transcript_json = null`; clarity and filler metrics absent; coaching runs on metrics alone.
- LLM failure → §11.3.
- Job crash → `failed` with error; SSE `error` event; row visible in Library with retry.
- Upload cleanup: an upload is deleted when no analysis and no unfinished job references its `source_sha256` — when its last analysis is deleted, and after a pipeline failure (a file that cannot be decoded fails the same way every time). Uploads of jobs failed by the infrastructure (worker crash, restart, runner unavailable) are kept so `POST /jobs/{id}/retry` can re-run them.
- Decode failure → job error `could not decode <file name>: not a supported audio/video file`; the ffmpeg command and stderr go to the server log only.

## 16. Testing

Backend fixtures (`conftest.py`): synthetic audio at 16 kHz — `tone(f0, dur)`, `tones_with_gaps(...)`, `vowel(f1, f2, f0, dur)` source-filter synth, `am_speech(...)` syllable-rate AM; test Postgres via `testcontainers` (or `DATABASE_URL` override); test RSA key pair with a mocked JWKS endpoint and a `make_token(sub, aud, exp)` helper.

- `test_pitch`: 120 Hz tone → `f0_median_hz` within 2 Hz; 100→200 Hz → `f0_range_st` ≈ 12.
- `test_phrasing`: 3 tones with 0.5 s and 1.5 s gaps → 3 phrases, 2 pauses, 1 long pause.
- `test_pace`: 4 Hz AM for 5 s → `syllable_count_est` within ±2 of 20.
- `test_intonation`: tail stepped +3 st → `up`; −3 st → `down`; flat → `flat`.
- `test_energy`: last 300 ms attenuated 10 dB → `trailing_off_count == 1`.
- `test_articulation`: low-passed vowel → lower HF ratio, steeper tilt; flattened AM → lower `modulation_depth`; {/i/, /a/} vs {schwa} → larger `vowel_space_area_hz2`.
- `test_clarity`: tail-attenuated word → `word_final_drop_count == 1`; probability fractions; rushed runs.
- `test_fillers`: counts incl. "you know".
- `test_determinism`: same fixture analysed twice in separate subprocesses → identical bytes.
- `test_comparison`: verdicts, `unchanged` threshold, config mismatch flag.
- `test_repo`: user scoping — user B cannot fetch user A's analysis; unique constraint.
- `test_number_check`: flags 17.3 when only 17.2 present; accepts rounded forms.
- `test_coach`: invalid then valid → one retry; two invalid → `None` + warning.
- `test_llm_contract`: parametrised over `registry.names()`, HTTP mocked (`pytest-httpx` for OpenAI-compatible, `anthropic` client patched) → output validates, `temperature == 0`.
- `test_openai_compatible_provider`: json_schema path, fallback on 400, `list_models`.
- `test_anthropic_provider`: forced tool-use request shape, tool input extraction.
- `test_auth`: valid token → 200 and user upserted; expired → 401; wrong audience → 401; wrong issuer → 401.
- `test_jobs`: stage progression recorded; exception → `failed`; startup marks stale jobs failed.
- `test_api_analyses`: upload → job → analysis (pipeline analysis mocked); other user → 404; delete removes files.
- `test_drive_oauth`: state signed/expired/tampered; refresh token encrypt/decrypt round-trip; callback redirect.
- `test_drive_cache`: key from id + modifiedTime, per-user directory, hit/miss.

Frontend: `LibraryPage` renders rows and opens drawer; `JobProgress` updates from mocked SSE; `ComparisonTable` arrows/verdicts; `CoachingPanel` shows warnings and unavailable state; `RequireAuth` redirects when logged out.

Not tested against real Google or Keycloak; both are mocked. A `scripts/smoke.sh` runs the compose stack and hits `/api/me` with a token obtained from Keycloak's token endpoint.

## 17. Engineering

- Backend: Python 3.11+, `pyproject.toml` (pip-installable), dependencies: fastapi, uvicorn, sqlalchemy ≥ 2, alembic, psycopg, pydantic ≥ 2, pydantic-settings, python-jose or PyJWT with cryptography, itsdangerous, cryptography (Fernet), praat-parselmouth, numpy, scipy, faster-whisper, pyyaml, google-api-python-client, google-auth-oauthlib, openai, anthropic, sse-starlette, pytest, pytest-httpx, testcontainers.
- Frontend: Node 20, pnpm.
- README: prerequisites (Docker, ffmpeg for local dev), Google Cloud OAuth web client setup, Keycloak first-run (realm imported, create a user), local OpenAI-compatible server (Ollama example), optional Anthropic key, `docker compose up`, dev mode, running tests.
- `.gitignore`: `.env`, `data/`, `backend/.venv/`, `frontend/node_modules/`, `frontend/dist/`.

## 18. Build order

1. Analysis core: config, audio, all `analysis/*`, schema, determinism test.
2. Transcription, fillers, syllables, clarity.
3. Postgres models, Alembic, repo, comparison.
4. FastAPI: settings, Keycloak auth, jobs, upload-only `POST /analyses`, analyses/comparisons endpoints, docker-compose with Keycloak + Postgres.
5. React: auth shell, Library, upload drawer, job progress, Analysis page, Compare page.
6. LLM path: base, registry, both providers, coach, number check, prompt, `/llm/models`, Coaching tab, re-run endpoint.
7. Drive per-user OAuth, Drive browser, cache.
8. README, `.env.example`, smoke script, hardening.

Each phase leaves the stack runnable.

## 19. Out of scope (v1)

- Coach/coachee or team sharing; admin UI.
- Per-user LLM endpoints or keys.
- Speaker diarisation; non-English syllable counting.
- Automatic formant ceiling selection.
- Horizontal scaling of job workers (Celery/Redis); single backend process.
- Service-account Drive access.

## 20. Amendments log

Every change to this spec made while implementing it, by plan. Plans 6, 7 and 8 record their amendments in the plan header; the entries for those plans are copied from there. Plans 1 to 4 recorded theirs in prose (self-review "deviation" notes and in-place spec edits); their entries below are derived from where the code differs from the original text of this spec, worded as "code does X; spec said Y", with the file that shows it. Plan 5 has no amendments header; its entries come from its self-review notes. Where a section above was already edited in place, it reflects the amendment and the original wording is quoted here.

### Plan 1: analysis core (`docs/superpowers/plans/2026-10-03-plan-1-analysis-core.md`)

1. §6.3 recording_quality: code clamps intensity at 0 dB before any metric (`backend/vocal_coach/analysis/tracks.py`, `INTENSITY_FLOOR_DB`); spec said nothing, so Praat's -300 dB for digital silence would have reached the noise floor.
2. §6.3 pace: code calls `find_peaks(prominence=syllable_peak_prominence_db, wlen=0.4 s)` (`analysis/pace.py`); spec said `find_peaks(prominence=syllable_peak_prominence_db)` with no window.
3. §6.3 energy: code anchors the final window at the end of the last phrase and takes the body as everything before it (`analysis/energy.py`); spec said "median speaking intensity excluding final `energy_window_s`" of the recording.
4. §6.3 articulation: code computes a two-band spectral tilt, (mean dB in `hf_band_hz` - mean dB in `lf_band_hz`) / log2 of the band-midpoint ratio over a Welch PSD (`analysis/articulation.py`, `_tilt`); spec said the slope of an LTAS (100 Hz bins) regressed on log2(f) over 500-8000 Hz.
5. §6.2 and §15: code adds `analysis.min_duration_s: 2.0` and reports `reasons: ["too_short"]` with every metric field null below it (`analysis/analyser.py`, `backend/config.yaml`); spec said audio under 2 s gives `["no_voiced_speech"]` with only pitch and intonation fields null.
6. §3.1: code passes a shared `Tracks` object (F0, intensity, samples extracted once) to each `analysis/*` module and computes recording quality in `analysis/quality.py`; spec said `compute(sound, cfg, **deps)` and recording_quality inside `analyser.py`. No output field changes.

### Plan 2: transcription (`docs/superpowers/plans/2026-10-03-plan-2-transcription.md`)

1. §7: code feeds faster-whisper the decoded 16 kHz float32 samples, with `vad_filter false` and `condition_on_previous_text false` (`backend/vocal_coach/transcription/transcriber.py`); spec said faster-whisper on the file, with neither option set.
2. §7: code keeps words from segments with `no_speech_prob > transcription.no_speech_exclude_prob` (default 0.6) in `segments`/`words` but leaves them out of `derived` (`transcription/run.py`, `backend/config.yaml`); spec had no such rule or config key.
3. §6.4 serialisation: code rounds transcript probabilities, log-probabilities and fractions to 6 decimals (`analysis/serialise.py`, `SIX_DECIMAL_FIELDS`); spec said 6 decimals for "ratios" only. No metrics key changes.

### Plan 3: storage and comparison (`docs/superpowers/plans/2026-10-03-plan-3-storage-comparison.md`)

1. §8: code's unique key is `(user_id, content_sha256, config_hash, analyser_version)` and adds index `(user_id, recorded_at)` (`backend/vocal_coach/storage/models.py`); spec said `unique (user_id, content_sha256, config_hash)` and no index, so a new analyser version would have collided with the stored row.
2. §9: code computes `delta` and the verdict from the first and last recordings that have the metric, marks rows with gaps `partial: true`, adds the verdict `unavailable` for a metric present in fewer than two recordings, and reports `analyser_version_mismatch` beside `config_mismatch` (`storage/comparison.py`); spec said consecutive and first-vs-current deltas with four verdicts and `config_mismatch` only.
3. §12: code's `GET /analyses` returns blob-free summaries with `limit`/`offset` pagination (`storage/repo.py`, `list_analysis_summaries`); spec said "list" with no paging or summary rule.

### Plan 4: API, auth and jobs (`docs/superpowers/plans/2026-10-04-plan-4-api-auth-jobs.md`)

1. §8: code adds `analyses.source_sha256` (hash of the uploaded bytes, names the stored upload) and `jobs.file_name`, `jobs.source_sha256`, `jobs.recorded_at` (`storage/models.py`); spec said `analyses.content_sha256` only and jobs without file fields.
2. §10: code runs jobs in a spawn-based `ProcessPoolExecutor` with `JOB_WORKERS` default 1, rebuilds the pool when a worker dies (`worker crashed: <reason>`) and answers 503 when it cannot (`backend/vocal_coach/jobs/runner.py`); spec said `ThreadPoolExecutor(max_workers=JOB_WORKERS, default 2)` with an in-process callback.
3. §10 and §12: code adds `GET /api/jobs?status=&limit=` (`api/jobs.py`); spec had no jobs list.
4. §10 and §12: code adds `POST /api/jobs/{id}/retry` returning 202 `{job_id}`, 404 foreign or missing, 409 not finished, 410 upload gone (`api/jobs.py`); spec had no retry endpoint (only "row visible in Library with retry" in §15).
5. §10 and §12: code ends an SSE stream open longer than an hour with a `timeout {message}` event and opens one short DB session per poll (`jobs/events.py`); spec said the stream emits `stage`, `progress`, `done`, `error` only.
6. §12: code adds `GET /api/analyses/{id}/raw/{kind}` for byte-stable `metrics` / `transcript` / `coaching` downloads (`api/analyses.py`); spec had none (JSONB reorders keys, so the UI cannot rebuild canonical bytes).
7. §12 and §15: code's `DELETE /api/analyses/{id}` removes the upload once no analysis and no unfinished job references its `source_sha256`; the pipeline deletes it after a decode failure, keeps it after an infrastructure failure, and reports decode failures as `could not decode <file name>: not a supported audio/video file` (`api/analyses.py`, `pipeline.py`); spec said "delete analysis and cached files".
8. §4 and §14: code adds `KEYCLOAK_JWKS_URL_OVERRIDE` so the backend container fetches JWKS over the compose network while `KEYCLOAK_ISSUER` stays the browser-visible URL (`settings.py`, `docker-compose.yml`); spec derived JWKS from the issuer only.
9. §14: code runs Keycloak with `start-dev --import-realm` and ships two realm files selected by `KEYCLOAK_REALM_FILE` (`keycloak/realm-export.dev.json` with a demo user and the password grant, the default; `keycloak/realm-export.json` production-shaped), both with an audience mapper so tokens carry `aud: vocal-coach-web` (`docker-compose.yml`, `keycloak/`); spec said `start --import-realm` with one realm file.
10. §3.1: code's backend image is Python 3.12 with a separate wheel-build stage (praat-parselmouth has no linux/aarch64 wheel) (`backend/Dockerfile`); spec said "python 3.11 + ffmpeg".

### Plan 5: React UI (`docs/superpowers/plans/2026-10-04-plan-5-react-ui.md`)

1. §13: code uses React 19, React Router 7, Tailwind v4, shadcn/ui and Recharts (`frontend/package.json`); spec said React 18. Nothing in the spec depends on 18.
2. §17: code uses npm with a committed `package-lock.json` (`frontend/package.json`, `frontend/Dockerfile`); spec said pnpm (made formal by Plan 8 amendment 5).

### Plan 6: LLM coaching (`docs/superpowers/plans/2026-10-04-plan-6-llm-coaching.md`)

1. §11.2 says the OpenAI-compatible provider uses the `openai` SDK. This plan uses `httpx` directly (already a dependency, trivially mockable with `pytest-httpx`, no second HTTP stack). Wire format is identical (`POST {base_url}/chat/completions`, `GET {base_url}/models`).
2. §11.2 says the Anthropic provider forces a single tool and sets `temperature 0`. Current Anthropic models (Opus 5.5, Sonnet 5.5, Fable 5.1) reject forced `tool_choice` and non-default `temperature` with HTTP 400. This plan uses structured outputs (`output_config.format` with the coaching JSON schema) and omits `temperature`; determinism comes from the strict schema, the fixed prompt, and the post-checks. Default model when `llm.model` is empty: `claude-opus-5-5`.
3. §12: `POST /analyses/{id}/coach` returns the updated `AnalysisDetail` (200). When `llm.enabled` is false it returns 503 `{"detail": "coaching is not enabled on this server"}`; when the model is not allowed, 422.

### Plan 7: Google Drive OAuth (`docs/superpowers/plans/2026-10-04-plan-7-drive-oauth.md`)

1. §5 scope: `https://www.googleapis.com/auth/drive.readonly` plus `https://www.googleapis.com/auth/userinfo.email`, so `google_email` can be stored and shown in Settings (the spec's table already has the column).
2. §12 `/me` gains `drive_configured: bool` (server has `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`); when false, `/drive/connect` and `/drive/files` return 503 `{"detail": "drive is not configured on this server"}` and the UI shows that text instead of a Connect button.
3. §5 cache: the Drive download is cached as the original file; the derived 16 kHz WAV is NOT kept beside it (the pipeline already derives it per job in a temp work dir and deletes it). Cache hit = no download.
4. §12 `POST /analyses` JSON body is `{"source": "drive", "file_ids": [...], "speaker_context": str | null, "llm": {"enabled": bool, "model": str | null}}`, 1 to 20 ids; response `{job_ids: [...]}` in the same order; a file id the user cannot read (404 at Google) → 404 `{"detail": "drive file <id> not found"}` and no jobs are created.

### Plan 8: README and hardening (`docs/superpowers/plans/2026-10-05-plan-8-readme-hardening.md`)

1. §9: a comparison row's verdict is `unchanged` when `abs(delta)` rounds to `0.0` at the metric's display precision (1 decimal; 2 for `modulation_depth`; 0 for counts), regardless of `min_meaningful_change_pct`. `ComparisonResult` gains `file_names: list[str | null]`.
2. §10: `jobs` gains `drive_file_id` and `drive_modified_time` so Drive jobs can be retried; `DELETE /api/jobs/{id}` dismisses a terminal job (404 for non-terminal or unknown).
3. §5: cache files are removed when the last analysis referencing that Drive file is deleted; total cache size per server is capped by `CACHE_MAX_MB` (default 2048) with least-recently-used eviction before each download; `DRIVE_MAX_MB` (default = `MAX_UPLOAD_MB`) caps Drive downloads. `GET /drive/files` also returns folders (`is_folder: true`, `size: null`) so the browser can navigate.
4. §14: the frontend image reads Keycloak settings at runtime from `/config.json` (generated by the nginx container entrypoint from `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`), replacing the build-time `VITE_KEYCLOAK_*` args; the Vite dev server serves a static `public/config.json`.
5. §17: Node version is 22 and the package manager is npm (not pnpm), matching what the project already uses; dependencies list reflects httpx-based providers (no `openai`, no `google-api-python-client`).
