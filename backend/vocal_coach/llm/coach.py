"""Coaching orchestration: call a provider, validate, retry once, attach post-check warnings.

Coaching never raises: every provider failure (known LLMError or an
unexpected exception) and every validation failure (even after the retry)
ends as a CoachResult with coaching=None and a readable warning.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from vocal_coach.llm.base import LLMError, LLMProvider
from vocal_coach.llm.markup_check import check_marked_up_example
from vocal_coach.llm.number_check import check_numbers
from vocal_coach.llm.prompts import load_system_prompt
from vocal_coach.llm.schema import COACHING_SCHEMA, CoachingOutput

log = logging.getLogger(__name__)

INVALID_OUTPUT = "invalid model output"
PREVIOUS_ERROR_MAX_CHARS = 500


@dataclass
class CoachResult:
    coaching: dict | None
    warnings: list[str]


def _call(provider: LLMProvider, prompt: str, payload: dict, model: str) -> tuple[dict | None, CoachResult | None]:
    """One provider call. Returns (raw, None) on success, or (None, failure result) otherwise."""
    try:
        raw = provider.generate_coaching(prompt, payload, COACHING_SCHEMA, model=model)
    except LLMError as e:
        return None, CoachResult(None, [f"coaching failed: {e}"])
    except Exception as e:
        log.warning("coaching provider raised %s", type(e).__name__)
        return None, CoachResult(None, [f"coaching failed: {type(e).__name__}"])
    return raw, None


def run_coaching(
    provider: LLMProvider,
    payload: dict,
    *,
    model: str,
    system_prompt: str | None = None,
    deadline_s: float | None = None,
) -> CoachResult:
    """deadline_s: when the first call has already taken longer than this, an invalid answer is
    not retried (a second slow call would double the wait); it ends as an invalid-output warning."""
    prompt = system_prompt or load_system_prompt()
    started = time.monotonic()

    raw, failure = _call(provider, prompt, payload, model)
    if failure is not None:
        return failure

    try:
        output = CoachingOutput.model_validate(raw)
    except ValidationError as err:
        if deadline_s is not None and time.monotonic() - started > deadline_s:
            log.warning("coaching validation retry skipped: deadline of %ss exceeded", deadline_s)
            return CoachResult(None, [f"{INVALID_OUTPUT}: {str(err)[:200]}"])
        retry_payload = payload | {"previous_error": str(err)[:PREVIOUS_ERROR_MAX_CHARS]}
        raw, failure = _call(provider, prompt, retry_payload, model)
        if failure is not None:
            return failure
        try:
            output = CoachingOutput.model_validate(raw)
        except ValidationError as err2:
            return CoachResult(None, [f"{INVALID_OUTPUT}: {str(err2)[:200]}"])

    output_dict = output.model_dump()
    warnings = check_numbers(output_dict, payload)
    markup_warning = check_marked_up_example(output_dict["marked_up_example"], payload.get("transcript_text"))
    if markup_warning:
        warnings = warnings + [markup_warning]
    return CoachResult(output_dict, warnings)
