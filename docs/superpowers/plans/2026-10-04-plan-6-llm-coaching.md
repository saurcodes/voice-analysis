# Vocal Coach — Plan 6: LLM Coaching Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Backend tasks run with `backend/.venv/bin/python` (system python lacks the deps); frontend tasks run from `frontend/` with npm.

**Goal:** Turn the deterministic metrics and transcript into validated, number-checked coaching JSON through a provider-agnostic LLM layer (OpenAI-compatible and Anthropic), stored per analysis, exposed in the API and the Coaching tab.

**Architecture:** A `vocal_coach/llm/` package: `LLMProvider` ABC + registry; two providers (`openai_compatible` over `httpx`, `anthropic` over the official `anthropic` SDK with structured outputs); a pure `payload.py` that prunes and caps the metrics/transcript/comparison; `coach.py` that calls the provider, validates `CoachingOutput`, retries once with the validation error, then runs the number and markup post-checks into `coaching_warnings`. The pipeline's existing `coach` stage calls it after `create_analysis` (and on a dedupe hit), never failing the job. The API flips `/me.llm_enabled`, serves `/llm/models` from the provider, and `POST /analyses/{id}/coach` re-runs coaching synchronously. The frontend regenerates types and wires the re-run dialog.

**Tech Stack:** Python 3.12, pydantic 2, httpx (already a dep) for the OpenAI-compatible provider, `anthropic>=1.11` (new runtime dep; it depends on `httpx2`, already in the dev lock), `pytest-httpx` (new dev dep) for HTTP mocking, FastAPI, SQLAlchemy; React/TanStack Query for the small frontend change.

**Spec:** `docs/superpowers/specs/2026-10-03-vocal-coach-design.md` §11 (LLM path), §12 (API rows `/me`, `/llm/models`, `/analyses/{id}/coach`), §15 (LLM failure degrades), §16 (tests `test_number_check`, `test_coach`, `test_llm_contract`, `test_openai_compatible_provider`).

**Spec amendments made by this plan (recorded here so the spec stays the authority):**
1. §11.2 says the OpenAI-compatible provider uses the `openai` SDK. This plan uses `httpx` directly (already a dependency, trivially mockable with `pytest-httpx`, no second HTTP stack). Wire format is identical (`POST {base_url}/chat/completions`, `GET {base_url}/models`).
2. §11.2 says the Anthropic provider forces a single tool and sets `temperature 0`. Current Anthropic models (Opus 5.5, Sonnet 5.5, Fable 5.1) reject forced `tool_choice` and non-default `temperature` with HTTP 400. This plan uses structured outputs (`output_config.format` with the coaching JSON schema) and omits `temperature`; determinism comes from the strict schema, the fixed prompt, and the post-checks. Default model when `llm.model` is empty: `claude-opus-5-5`.
3. §12: `POST /analyses/{id}/coach` returns the updated `AnalysisDetail` (200). When `llm.enabled` is false it returns 503 `{"detail": "coaching is not enabled on this server"}`; when the model is not allowed, 422.

## Global Constraints

- `ANALYSER_VERSION` and `config_hash` are untouched: the `llm` section of `config.yaml` is NOT part of `config_hash` (it already only covers `analysis` + `articulation`). Pinned versions of parselmouth/numpy/scipy must not change.
- No model name hard-coded except the Anthropic default fallback `claude-opus-5-5` when `llm.model` is empty. Users pick models from `GET /api/llm/models`; `allowed_models` (non-empty) filters that list and rejects others with 422.
- Keys come only from environment: `OPENAI_COMPAT_API_KEY` (optional), `ANTHROPIC_API_KEY`; never from config.yaml or the API.
- Coaching never fails a job or an analysis: every provider exception, timeout, invalid output, or missing key ends as `coaching_json = null` + `coaching_warnings = [message]` and the pipeline continues to `done`.
- Spec §11.3 payload rules verbatim: drop `per_phrase`, `per_phrase_end_drop_db`, `words`; keep `long_pauses`, `eaten_words`, `rushed_runs`, `low_conf_words` capped at 20 each; `comparison` = deltas vs the user's previous analysis (by `recorded_at`, excluding itself) or `null`.
- `CoachingOutput` exactly `{what_improved: string[], what_is_lacking: string[], next_steps: string[], marked_up_example: string}`; `additionalProperties: false`; all four required.
- Number post-check: allowed set = every numeric leaf of the payload's `metrics`, `transcript_derived`, `comparison` at 0, 1, 2 decimals; unmatched numeric tokens in the four output fields (ignoring `//`) → `coaching_warnings`.
- Markup post-check: `marked_up_example` de-marked (remove `//`, `↘`, lowercase, strip punctuation) must be a contiguous word subsequence of the transcript text; otherwise warning `"marked_up_example does not match the transcript"`.
- Tests run `pytest -W error`; no network in tests (`pytest-httpx` blocks unmocked requests; the Anthropic client is patched). All 249 existing tests stay green.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **Provider unreachable (Ollama down, DNS failure, 5xx) during a job:** the job still reaches `done`, the analysis row exists, `coaching_warnings` carries a readable message (no stack trace, no URL with a key). Test in Task 6.
2. **Model returns valid JSON with extra keys or a missing field:** first attempt fails validation, the retry carries `previous_error`, a valid second answer is stored; two failures store null + `["invalid model output: ..."]`. Test in Task 3.
3. **Model cites a number that is a re-rounding (17.26 → 17.3) or an invented one (17.5):** `17.3` is accepted (2-decimal source rounds to 1 decimal), `17.5` is flagged with the token in the warning. Test in Task 2.
4. **Transcript absent (whisper failed) or empty words:** payload has `transcript_text: ""`, `transcript_derived: null`; the markup check is skipped with the warning `"no transcript available for marked_up_example"`; coaching still runs on metrics alone. Test in Task 2 and Task 6.
5. **`llm_model` requested that is not in `allowed_models`, or `allowed_models` empty and provider listing fails:** upload is accepted (job runs) but coaching stores the warning `"model X is not allowed on this server"`; `POST /coach` returns 422; `/llm/models` returns 503 with detail when the provider cannot list. Test in Task 6.

---

### Task 1: LLM config, settings, output schema, provider base and registry

**Files:**
- Modify: `backend/vocal_coach/config.py` (add `LLMConfig`, field `llm` on `AppConfig`; `config_hash` unchanged)
- Modify: `backend/vocal_coach/settings.py` (add `openai_compat_api_key: str | None = None`, `anthropic_api_key: str | None = None`)
- Modify: `backend/pyproject.toml` (deps `anthropic>=1.11`; dev `pytest-httpx>=0.36`), regenerate `backend/requirements.lock` the same way it was produced (`.venv/bin/pip freeze` after `pip install -e ".[dev]"`; check the file header for the exact command and reuse it)
- Create: `backend/vocal_coach/llm/__init__.py`, `backend/vocal_coach/llm/schema.py`, `backend/vocal_coach/llm/base.py`, `backend/vocal_coach/llm/registry.py`, `backend/vocal_coach/llm/providers/__init__.py`
- Test: `backend/tests/test_llm_registry.py`, extend `backend/tests/test_config.py`

**Interfaces (Produces):**

```python
# config.py
class LLMConfig(BaseModel):
    enabled: bool = False
    provider: str = "openai_compatible"
    base_url: str = "http://localhost:11434/v1"
    model: str = ""
    allowed_models: list[str] = []
    seed: int = 42
    timeout_s: float = 120.0
    max_output_tokens: int = 2048

class AppConfig(BaseModel):
    ...
    llm: LLMConfig            # loaded from raw["llm"]; missing section → LLMConfig() defaults (enabled False)

# llm/schema.py
class CoachingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    what_improved: list[str]
    what_is_lacking: list[str]
    next_steps: list[str]
    marked_up_example: str
COACHING_SCHEMA: dict  # JSON schema: type object, the four properties (arrays of string / string), required all four, additionalProperties False

# llm/base.py
class LLMError(RuntimeError): """Any provider failure (network, auth, HTTP status, non-JSON answer)."""
class LLMProvider(ABC):
    name: str
    def __init__(self, cfg: LLMConfig, settings: Settings) -> None
    @abstractmethod
    def generate_coaching(self, system_prompt: str, user_payload: dict, schema: dict, *, model: str) -> dict: ...
        # returns the parsed JSON object the model produced (NOT yet validated); raises LLMError on failure
    def list_models(self) -> list[str]: return []   # raises LLMError on failure

# llm/registry.py
def register(name: str) -> Callable[[type[LLMProvider]], type[LLMProvider]]
def get_provider(name: str, cfg: LLMConfig, settings: Settings) -> LLMProvider   # KeyError → LLMError(f"unknown LLM provider {name!r}")
def names() -> list[str]
# importing vocal_coach.llm.providers registers both providers (Tasks 4 and 5 add the modules; __init__ imports them)
```

- [ ] **Step 1: Failing tests**

`backend/tests/test_llm_registry.py`:

```python
import pytest
from vocal_coach.config import LLMConfig
from vocal_coach.llm.base import LLMError, LLMProvider
from vocal_coach.llm.registry import get_provider, names, register
from vocal_coach.llm.schema import COACHING_SCHEMA, CoachingOutput
from vocal_coach.settings import Settings


def test_register_and_get_provider():
    @register("fake_for_test")
    class Fake(LLMProvider):
        name = "fake_for_test"
        def generate_coaching(self, system_prompt, user_payload, schema, *, model):
            return {}
    settings = Settings(_env_file=None)
    p = get_provider("fake_for_test", LLMConfig(), settings)
    assert isinstance(p, Fake) and "fake_for_test" in names()


def test_unknown_provider_is_llm_error():
    with pytest.raises(LLMError, match="unknown LLM provider"):
        get_provider("nope", LLMConfig(), Settings(_env_file=None))


def test_schema_matches_model():
    assert COACHING_SCHEMA["additionalProperties"] is False
    assert set(COACHING_SCHEMA["required"]) == {"what_improved", "what_is_lacking", "next_steps", "marked_up_example"}
    with pytest.raises(Exception):
        CoachingOutput.model_validate({"what_improved": [], "what_is_lacking": [], "next_steps": [], "marked_up_example": "x", "extra": 1})
```

Extend `backend/tests/test_config.py`:

```python
def test_llm_config_loaded_and_not_in_hash(cfg):
    assert cfg.llm.provider in {"openai_compatible", "anthropic"}
    assert cfg.llm.timeout_s == 120
    from vocal_coach.config import config_hash
    changed = cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"model": "other"})})
    assert config_hash(changed) == config_hash(cfg)
```

- [ ] **Step 2: Run, implement, run**

`cd backend && .venv/bin/pip install -e ".[dev]"` after editing `pyproject.toml`; regenerate `requirements.lock`. Implement; `.venv/bin/python -m pytest tests/test_llm_registry.py tests/test_config.py -q -W error` passes; full suite still 249+ green.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/requirements.lock backend/vocal_coach/config.py backend/vocal_coach/settings.py backend/vocal_coach/llm backend/tests/test_llm_registry.py backend/tests/test_config.py
git commit -m "feat(llm): LLMConfig, provider base and registry, CoachingOutput schema, anthropic dependency

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Payload builder, number check, markup check, system prompt

**Files:**
- Create: `backend/vocal_coach/llm/payload.py`, `backend/vocal_coach/llm/number_check.py`, `backend/vocal_coach/llm/markup_check.py`, `backend/vocal_coach/llm/prompts/coach.md`, `backend/vocal_coach/llm/prompts/__init__.py` (exposes `load_system_prompt() -> str`)
- Modify: `backend/pyproject.toml` package data so `prompts/coach.md` ships in the wheel (`[tool.setuptools.package-data] "vocal_coach.llm.prompts" = ["*.md"]` or the hatch equivalent; check the build backend in use)
- Test: `backend/tests/test_llm_payload.py`, `backend/tests/test_number_check.py`, `backend/tests/test_markup_check.py`

**Interfaces (Produces):**

```python
# payload.py
CAP = 20
DROP_PATHS = ("intonation.per_phrase", "energy.per_phrase_end_drop_db")   # also any key named per_phrase anywhere under metrics
def build_payload(metrics: dict, transcript: dict | None, comparison: dict | None, speaker_context: str | None) -> dict
# → {"metrics": pruned, "transcript_text": transcript["text"] or "", "transcript_derived": pruned derived or None,
#    "comparison": comparison or None, "speaker_context": speaker_context or None}
# pruning: deep-copy; delete keys "per_phrase" and "per_phrase_end_drop_db" at any depth under metrics;
# lists at keys long_pauses, eaten_words, rushed_runs, low_conf_words truncated to CAP (first 20); transcript["words"] never included.

# number_check.py
def numeric_leaves(obj) -> list[float]            # recursive over dict/list; ints and floats; bools excluded
def allowed_forms(values: Iterable[float]) -> set[str]   # f"{v:.0f}", f"{v:.1f}", f"{v:.2f}" and the bare int form for integers; also forms without trailing zeros ("17.30"→"17.3")
NUMBER_RE = re.compile(r"(?<![\w/])[-+]?\d+(?:\.\d+)?(?![\w/])")   # ignores "//" and digits glued to letters (e.g. "F0", "16k")
def extract_numbers(text: str) -> list[str]
def check_numbers(output: dict, payload: dict) -> list[str]
# warnings like f"number {tok} in {field} does not match any metric value"; fields scanned: the four CoachingOutput fields (lists joined)

# markup_check.py
MARKS = ("//", "↘")
def demark(text: str) -> list[str]   # remove marks, lowercase, strip punctuation, split on whitespace
def check_marked_up_example(example: str, transcript_text: str | None) -> str | None
# None when demark(example) is a contiguous subsequence of demark(transcript_text) (case-insensitive);
# "no transcript available for marked_up_example" when transcript_text is falsy;
# "marked_up_example does not match the transcript" otherwise; empty example → "marked_up_example is empty"
```

`prompts/coach.md` (full text, written verbatim by the implementer):

```
You are a vocal delivery coach. You receive deterministic acoustic metrics, a transcript, derived transcript statistics, an optional comparison with the speaker's previous recording, and an optional speaker context.

Rules:
- Cite metrics by their name and value exactly as given. Never invent numbers and never re-round them.
- When a metric block has "low_confidence": true, say so when you cite it.
- Articulation and clarity metrics (hf_energy_ratio_db, modulation_depth, vowel_space, weak_peak_fraction, eaten_words, rushed_runs, low_conf_words) are indirect proxies. Phrase them as "suggests" and pair each claim with concrete words from eaten_words or rushed_runs when available.
- Focus on the 1 to 3 highest-impact changes. Be specific and practical.
- what_improved: what moved in the right direction versus the previous recording (empty list when there is no comparison).
- what_is_lacking: the main weaknesses, each tied to a cited metric.
- next_steps: concrete exercises or instructions the speaker can apply in the next recording.
- marked_up_example: 2 to 3 real consecutive sentences copied from the transcript with the words unchanged, marked up with // for a 1 to 1.5 second pause, CAPITALS for a stressed word, and ↘ for a falling finish. If there is no transcript, use an empty string.
- Respond only with JSON matching the provided schema. No prose outside the JSON.
```

- [ ] **Step 1: Failing tests**

`test_llm_payload.py`: metrics with `intonation.per_phrase` and `energy.per_phrase_end_drop_db` and 25 `long_pauses` → payload drops both keys, caps list to 20, keeps `transcript_text`, excludes `words`; `transcript=None` → `transcript_text == ""` and `transcript_derived is None`; `comparison=None` passes through as `None`.

`test_number_check.py`:

```python
def test_flags_rerounded_and_invented_numbers():
    payload = {"metrics": {"pitch": {"f0_range_st": 17.26}}, "transcript_derived": None, "comparison": None}
    out = {"what_improved": [], "what_is_lacking": ["range 17.3 st", "range 17.5 st"], "next_steps": [], "marked_up_example": "pause // here"}
    warnings = check_numbers(out, payload)
    assert any("17.5" in w for w in warnings) and not any("17.3" in w for w in warnings)

def test_accepts_integer_forms_and_ignores_marks():
    payload = {"metrics": {"phrasing": {"pause_count": 4, "pauses_per_min": 12.0}}, "transcript_derived": None, "comparison": None}
    out = {"what_improved": ["4 pauses", "12 per min", "12.0 per min"], "what_is_lacking": [], "next_steps": [], "marked_up_example": "F0 // 16k"}
    assert check_numbers(out, payload) == []
```

`test_markup_check.py`: `"we WILL win // today ↘."` vs transcript `"So we will win today, right?"` → `None`; `"we lose today"` → mismatch warning; `transcript_text=None` → no-transcript warning; `""` → empty warning.

- [ ] **Step 2: Run, implement, run; load_system_prompt() returns the md text; commit**

```bash
git add backend/vocal_coach/llm backend/pyproject.toml backend/tests/test_llm_payload.py backend/tests/test_number_check.py backend/tests/test_markup_check.py
git commit -m "feat(llm): coaching payload builder, number and markup post-checks, system prompt

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Coaching orchestration with one retry

**Files:**
- Create: `backend/vocal_coach/llm/coach.py`
- Test: `backend/tests/test_coach.py`, `backend/tests/fake_llm.py` (shared fake provider for Tasks 3, 6)

**Interfaces (Produces):**

```python
# llm/coach.py
@dataclass
class CoachResult:
    coaching: dict | None
    warnings: list[str]

INVALID_OUTPUT = "invalid model output"
def run_coaching(provider: LLMProvider, payload: dict, *, model: str, system_prompt: str | None = None) -> CoachResult
# 1. attempt = provider.generate_coaching(system_prompt or load_system_prompt(), payload, COACHING_SCHEMA, model=model)
# 2. validate with CoachingOutput.model_validate; on ValidationError retry ONCE with payload | {"previous_error": str(err)}
# 3. second failure → CoachResult(None, [f"{INVALID_OUTPUT}: {err_summary}"]) where err_summary is the first 200 chars of the error
# 4. LLMError (either attempt) → CoachResult(None, [f"coaching failed: {message}"]) (no retry on provider errors)
# 5. success → warnings = check_numbers(output, payload) + ([m] if (m := check_marked_up_example(output["marked_up_example"], payload["transcript_text"])) else [])
#    CoachResult(output_dict, warnings)

# tests/fake_llm.py
class FakeProvider(LLMProvider):
    name = "fake"
    def __init__(self, answers: list[dict | Exception], models: list[str] = ("fake-1",)) -> None   # answers popped per call; Exception instances are raised
    calls: list[dict]   # each call's payload (so tests can assert previous_error presence)
```

- [ ] **Step 1: Failing tests** (`test_coach.py`): invalid then valid → one retry, second call payload has `previous_error`, result stored; two invalid → `None` + warning starting `invalid model output`; `LLMError("boom")` → `None` + `"coaching failed: boom"` and exactly one call; valid output with an invented number and non-matching example → both warnings present, coaching kept.

- [ ] **Step 2: Implement, run, commit**

```bash
git add backend/vocal_coach/llm/coach.py backend/tests/test_coach.py backend/tests/fake_llm.py
git commit -m "feat(llm): run_coaching with validation retry and post-check warnings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: OpenAI-compatible provider (httpx)

**Files:**
- Create: `backend/vocal_coach/llm/providers/openai_compatible.py`
- Modify: `backend/vocal_coach/llm/providers/__init__.py` (import the module so `@register("openai_compatible")` runs)
- Test: `backend/tests/test_openai_compatible_provider.py` (uses the `httpx_mock` fixture from `pytest-httpx`)

**Behaviour:**
- `POST {base_url}/chat/completions` with JSON `{"model": model, "temperature": 0, "seed": cfg.seed, "max_tokens": cfg.max_output_tokens, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": json.dumps(user_payload, sort_keys=True)}], "response_format": {"type": "json_schema", "json_schema": {"name": "coaching_output", "strict": True, "schema": schema}}}`; header `Authorization: Bearer {settings.openai_compat_api_key}` only when the key is set; timeout `cfg.timeout_s`.
- On HTTP 4xx from the first attempt: retry once with `response_format = {"type": "json_object"}` and the schema appended to the system prompt as `"\n\nThe JSON must match this schema exactly:\n" + json.dumps(schema)`.
- Parse `choices[0].message.content` as JSON; non-JSON or missing → `LLMError("model returned non-JSON content")`. 5xx, connection errors, timeouts → `LLMError` with status/`type(e).__name__` (never the body).
- `list_models()` → `GET {base_url}/models` → `[m["id"] for m in data["data"]]` sorted; errors → `LLMError`.
- A fresh `httpx.Client(timeout=cfg.timeout_s)` per call is fine (coaching is rare), or one client per provider instance; either way close it.

- [ ] **Step 1: Failing tests**: json_schema path sends the strict schema and parses the answer; 400 on first call → second call uses `json_object` and the schema text in the system prompt; 500 → `LLMError`; non-JSON content → `LLMError`; `list_models` parses ids; key header present only when configured.

- [ ] **Step 2: Implement, run, commit**

```bash
git add backend/vocal_coach/llm/providers backend/tests/test_openai_compatible_provider.py
git commit -m "feat(llm): OpenAI-compatible provider over httpx with json_schema and json_object fallback

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Anthropic provider (official SDK, structured outputs) and the cross-provider contract test

**Files:**
- Create: `backend/vocal_coach/llm/providers/anthropic_provider.py`
- Modify: `backend/vocal_coach/llm/providers/__init__.py`
- Test: `backend/tests/test_anthropic_provider.py`, `backend/tests/test_llm_contract.py`

**Behaviour (from the claude-api skill, Python):**

```python
import anthropic
from anthropic.types import Message

DEFAULT_MODEL = "claude-opus-5-5"

@register("anthropic")
class AnthropicProvider(LLMProvider):
    name = "anthropic"
    def __init__(self, cfg, settings):
        super().__init__(cfg, settings)
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=cfg.timeout_s, max_retries=1)

    def generate_coaching(self, system_prompt, user_payload, schema, *, model):
        try:
            response: Message = self._client.messages.create(
                model=model or DEFAULT_MODEL,
                max_tokens=self.cfg.max_output_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": json.dumps(user_payload, sort_keys=True)}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIStatusError as e:
            raise LLMError(f"anthropic error {e.status_code}") from e
        except anthropic.APIConnectionError as e:   # includes APITimeoutError
            raise LLMError(f"anthropic connection error: {type(e).__name__}") from e
        if response.stop_reason == "refusal":
            raise LLMError("anthropic declined the request")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None: raise LLMError("model returned no text")
        try: return json.loads(text)
        except json.JSONDecodeError as e: raise LLMError("model returned non-JSON content") from e

    def list_models(self):
        try: return sorted(m.id for m in self._client.models.list())
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e: raise LLMError(...) from e
```

No `temperature`, no `tool_choice`, no `thinking` parameter (adaptive by default). Exception class names must match the installed SDK (`anthropic.APIStatusError`, `anthropic.APIConnectionError`, `anthropic.APITimeoutError` is a subclass of `APIConnectionError`); verify with `python -c "import anthropic; print(anthropic.APITimeoutError.__mro__)"`.

- [ ] **Step 1: Failing tests**

`test_anthropic_provider.py`: patch `anthropic.Anthropic` with a fake whose `messages.create` records kwargs and returns an object with `stop_reason="end_turn"` and `content=[SimpleNamespace(type="text", text=json.dumps(valid))]` → assert kwargs include `output_config={"format": {"type": "json_schema", "schema": COACHING_SCHEMA}}`, `system`, and NO `temperature`/`tool_choice`; `stop_reason="refusal"` → `LLMError`; `messages.create` raising `anthropic.APIStatusError` (construct with `message`, `response=httpx2.Response(500, request=httpx2.Request("POST", "x"))`, `body=None`) → `LLMError("anthropic error 500")`; missing key → `LLMError` at construction; `list_models` sorts ids.

`test_llm_contract.py`, parametrised over `registry.names()` (must be exactly `["anthropic", "openai_compatible"]` after importing `vocal_coach.llm.providers`): for `openai_compatible` use `httpx_mock` returning a valid answer and assert the request body has `temperature == 0`; for `anthropic` use the patched client. Both: `run_coaching(provider, payload, model="m")` returns `coaching` validating as `CoachingOutput` and `warnings == []` for a numerically faithful answer.

- [ ] **Step 2: Implement, run, commit**

```bash
git add backend/vocal_coach/llm/providers backend/tests/test_anthropic_provider.py backend/tests/test_llm_contract.py
git commit -m "feat(llm): Anthropic provider with structured outputs; cross-provider contract test

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Pipeline coach stage, previous-analysis comparison, API endpoints, compose env

**Files:**
- Modify: `backend/vocal_coach/storage/repo.py` (add `previous_analysis(session, user_id, *, before: datetime, exclude_id: uuid.UUID) -> Analysis | None`: newest row with `recorded_at < before`, or if none, the newest with `recorded_at == before and id != exclude_id`; user-scoped)
- Create: `backend/vocal_coach/llm/service.py`
- Modify: `backend/vocal_coach/pipeline.py` (coach stage + dedupe-hit coaching)
- Modify: `backend/vocal_coach/api/llm.py`, `backend/vocal_coach/api/me.py`
- Modify: `docker-compose.yml` (pass `OPENAI_COMPAT_API_KEY`, `ANTHROPIC_API_KEY` through to `backend`; `.env.example` already lists them), `backend/openapi.json` (re-export), `backend/README.md` (LLM section: config keys, env keys, providers, how coaching degrades)
- Test: `backend/tests/test_llm_service.py`, extend `backend/tests/test_pipeline.py`, `backend/tests/test_repo.py`, `backend/tests/test_api_llm.py`

**Interfaces (Produces):**

```python
# llm/service.py  (the only module pipeline and API import)
MODEL_NOT_ALLOWED = "model {model!r} is not allowed on this server"
NO_MODEL = "no LLM model configured"

def resolve_model(cfg: LLMConfig, requested: str | None) -> tuple[str | None, str | None]
# → (model, warning). requested or cfg.model; empty → (None, NO_MODEL) unless provider is anthropic (then DEFAULT_MODEL);
#   if cfg.allowed_models and model not in cfg.allowed_models → (None, MODEL_NOT_ALLOWED.format(model=model))

def coaching_comparison(session, user_id, row) -> dict | None
# previous = repo.previous_analysis(...); None → None; else compare([from_row(previous), from_row(row)], cfg.comparison).model_dump(mode="json")
# keep only: {"previous_recorded_at", "rows": [{"path", "values", "delta", "verdict"}], "config_mismatch", "analyser_version_mismatch"}

def coach_analysis(session, cfg: AppConfig, settings: Settings, user_id, analysis_id, *, model: str | None, speaker_context: str | None, provider: LLMProvider | None = None) -> Analysis | None
# row = repo.get_analysis; None → None. speaker_context None keeps the row's. model, warn = resolve_model → warn → set_coaching(None, [warn]).
# provider = provider or get_provider(cfg.llm.provider, cfg.llm, settings) (LLMError → set_coaching(None, [f"coaching failed: {e}"]))
# payload = build_payload(row.metrics_json, row.transcript_json, coaching_comparison(...), speaker_context)
# result = run_coaching(provider, payload, model=model); repo.set_coaching(..., coaching_json=result.coaching, coaching_warnings=result.warnings or None)
# Every exception path logs at WARNING with the analysis id and never raises.

def list_models(cfg: LLMConfig, settings: Settings) -> list[str]   # provider.list_models() filtered by allowed_models when set; LLMError propagates
```

Pipeline (`run_pipeline`): after `create_analysis`, `progress("coach", 90)`; if `req.llm_enabled and cfg.llm.enabled`: `coach_analysis(session, cfg, settings, req.user_id, row.id, model=req.llm_model, speaker_context=req.speaker_context, provider=llm_provider)` where `run_pipeline` gains a keyword `llm_provider: LLMProvider | None = None` (tests inject `FakeProvider`); then `progress("done", 100)`. Dedupe hit: when `req.llm_enabled and cfg.llm.enabled`, run `coach_analysis` on `existing.id` (with the new speaker context) before returning. If `req.llm_enabled` but `cfg.llm.enabled` is false: `set_coaching(None, ["coaching is not enabled on this server"])`.

API:
- `GET /llm/models` → `{enabled: cfg.llm.enabled, provider: cfg.llm.provider or None, models: list_models(...)}`; when disabled → `{enabled: False, provider: None, models: []}` without calling the provider; `LLMError` → 503 `{"detail": "LLM provider unavailable: <message>"}`. Run the provider call in `asyncio.to_thread` (make the route `async def`).
- `GET /me` → `llm_enabled=cfg.llm.enabled`, `llm_provider=cfg.llm.provider if enabled else None`.
- `POST /analyses/{id}/coach` body `CoachRequest {speaker_context: str | None = None, model: str | None = None}` → 404 if not found; 503 if disabled; 422 `{"detail": MODEL_NOT_ALLOWED...}` when `resolve_model` rejects (checked before running); else `await asyncio.to_thread(coach_analysis, ...)` and return `AnalysisDetail` (reuse the builder in `api/analyses.py`; export it as a function if it is inline). `responses` documented for 404/422/503 so OpenAPI is typed.

- [ ] **Step 1: Failing tests**

`test_repo.py` additions: `previous_analysis` returns the newest earlier row for the same user, ignores other users, returns None when none, and handles equal `recorded_at` via `exclude_id`.

`test_llm_service.py`: `resolve_model` cases (requested allowed; requested not allowed → warning; empty with openai → NO_MODEL; empty with anthropic → `claude-opus-5-5`); `coaching_comparison` None without a previous row and shaped rows with one; `coach_analysis` with `FakeProvider` stores coaching; with `FakeProvider([LLMError("down")])` stores `None` + `["coaching failed: down"]` (Review Focus 1); with `transcript_json=None` the payload has `transcript_text == ""` and the warnings include the no-transcript message (Review Focus 4).

`test_pipeline.py` additions (ffmpeg-gated like the others): `llm_enabled=True`, `cfg` copy with `llm.enabled=True`, `llm_provider=FakeProvider([valid])` → row has `coaching_json`; stage sequence unchanged; dedupe hit with `llm_enabled=True` coaches the existing row; `FakeProvider([LLMError("down")])` → job still completes, `coaching_warnings == ["coaching failed: down"]`.

`test_api_llm.py` (using `make_test_app`; check how it injects `cfg` and add a parameter or monkeypatch `app.state.cfg`): `/llm/models` disabled → `{enabled: false, models: []}`; enabled with provider patched (`monkeypatch.setattr("vocal_coach.llm.service.get_provider", lambda *a, **k: FakeProvider([], models=["a", "b"]))`) → `["a", "b"]`; `allowed_models=["b"]` → `["b"]`; provider raising → 503; `/me.llm_enabled` mirrors config; `POST /analyses/{id}/coach` 404 / 503 / 422 / 200 with coaching present (Review Focus 5).

- [ ] **Step 2: Implement; re-export OpenAPI (`cd backend && PYTHONPATH=. .venv/bin/python scripts/export_openapi.py`); README; compose env; full suite `-W error` green; commit**

```bash
git add backend/vocal_coach backend/tests backend/openapi.json backend/README.md docker-compose.yml
git commit -m "feat(llm): coach stage in the pipeline, previous-analysis comparison, /llm/models, /me, POST coach

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Frontend wiring: regenerated types, re-run coaching dialog, model select

**Files:**
- Modify: `frontend/src/api/types.ts` (via `npm run gen:api`, never by hand), `frontend/src/api/hooks.ts` (add `useCoachAnalysis()` mutation: `POST /api/analyses/{id}/coach` with `{speaker_context?, model?}` → invalidates `["vc","analysis",id]` and `["vc","summaries"]`), `frontend/src/components/analysis/CoachingPanel.tsx` (re-run dialog), `frontend/src/pages/AnalysisPage.tsx` (pass `analysisId`, `speakerContext`), `frontend/src/test/handlers.ts` + `fixtures.ts` (coach endpoint handler returning a detail with coaching; `llm/models` handler variant with `enabled: true`), `frontend/README.md` (one paragraph: coaching needs server config)
- Test: `frontend/src/components/analysis/CoachingPanel.test.tsx` (new), extend `frontend/src/components/library/AnalyseDrawer.test.tsx`

**Behaviour:**
- `CoachingPanel` props become `{analysisId: string, coaching, coachingWarnings, speakerContext: string | null}`. "Re-run coaching" button: disabled with the existing text when `useMe().data?.llm_enabled === false`; enabled otherwise and opens a shadcn `Dialog` "Re-run coaching" with a `Textarea` (prefilled `speakerContext`), a `Select` of models from `useLlmModels()` (default = first, or the stored one if the detail carries it; if the list is empty show "Server default" option sending `model: null`), and a primary button "Run". While pending: button disabled with "Running…" text (use three dots "...", no ellipsis character), spinner-free. Success: dialog closes, panel shows the new coaching. `ApiError` → inline `role="alert"` with `detail` (422 for a disallowed model, 503 when disabled mid-way).
- Present-state render (already written) now gets a test with a full coaching fixture: three lists and the `marked_up_example` in a `pre.num`; warnings list rendered under a "Checks" heading with the `--warning` icon + text.
- `AnalyseDrawer`: when `llm_enabled` true (handler variant), the switch is enabled and toggling it reveals the model `Select` from `useLlmModels` (existing branch); submitting sends `llm_enabled: true`, `llm_model: <selected>` (assert via the mocked `uploadAnalysis` call args).
- Zero em-dashes; `.num` only on numbers.

- [ ] **Step 1: Failing tests** as described; `npm test`, `npm run build`, `npm run lint` (zero warnings).

- [ ] **Step 2: Implement (invoke the design skill before UI changes), run, commit**

```bash
git add frontend
git commit -m "feat(frontend): re-run coaching dialog with model select; regenerated API types

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage §11:** 11.1 interface + registry (T1); 11.2 providers (T4, T5; amendments 1 and 2 recorded above), server-wide settings and user model choice (T6 `/llm/models`, `resolve_model`); 11.3 payload, output, validation flow, retry, markup rule (T2, T3); 11.4 prompt (T2); 11.5 number check (T2). §12 rows `/me`, `/llm/models`, `/coach` (T6). §15 LLM failure degrades (T3, T6). §16 named tests present (T2 `test_number_check`, T3 `test_coach`, T5 `test_llm_contract`, T4 `test_openai_compatible_provider`). §13 Coaching panel shows warnings and re-run (T7).
- **Placeholders:** none; every module has its signature and behaviour spelled out; prompt text given in full.
- **Type consistency:** `LLMProvider.__init__(cfg, settings)` (T1) used by both providers (T4, T5) and `get_provider` (T1, T6); `run_coaching(provider, payload, *, model, system_prompt=None) -> CoachResult` (T3) consumed by `coach_analysis` (T6) and the contract test (T5); `FakeProvider(answers, models)` (T3) used in T5/T6; `build_payload` keys `transcript_text`/`transcript_derived` (T2) read by `check_marked_up_example` call in T3 and asserted in T6; `COACHING_SCHEMA` (T1) passed by T3 and asserted in T4/T5.
- **Review Focus pins:** 1 → `test_llm_service.py`/`test_pipeline.py` provider-down cases (T6); 2 → `test_coach.py` (T3); 3 → `test_number_check.py` (T2); 4 → `test_markup_check.py` (T2) + `test_llm_service.py` no-transcript (T6); 5 → `test_api_llm.py` + `resolve_model` tests (T6).
- **Known limits:** no live LLM in tests. The final review may run one real coaching call if `ANTHROPIC_API_KEY` or a local Ollama is available on this machine; otherwise the controller verifies with `FakeProvider` only and says so. Refusal fallbacks (`fallbacks: "default"`) are not enabled: coaching text is benign and a declined request already degrades to a warning.
