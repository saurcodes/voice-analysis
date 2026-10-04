"""Pure payload builder: prunes and caps metrics/transcript for the LLM.

Operates on plain dicts (the stored JSON), never on pydantic objects. The
caller is responsible for loading metrics_json / transcript_json / comparison
from storage before calling build_payload.
"""
from __future__ import annotations

import copy

CAP = 20

# Dropped at any depth under metrics (and, harmlessly, under transcript derived).
_DROP_KEYS = {"per_phrase", "per_phrase_end_drop_db"}

# Capped to the first CAP items, at any depth under metrics or transcript derived.
_CAP_KEYS = {"long_pauses", "eaten_words", "rushed_runs", "low_conf_words"}


def _prune(obj):
    if isinstance(obj, dict):
        pruned = {}
        for key, value in obj.items():
            if key in _DROP_KEYS:
                continue
            if key in _CAP_KEYS and isinstance(value, list):
                pruned[key] = [_prune(item) for item in value[:CAP]]
            else:
                pruned[key] = _prune(value)
        return pruned
    if isinstance(obj, list):
        return [_prune(item) for item in obj]
    return obj


def build_payload(
    metrics: dict,
    transcript: dict | None,
    comparison: dict | None,
    speaker_context: str | None,
) -> dict:
    """Build the pruned payload sent to the LLM provider.

    - metrics: deep-copied then pruned (per_phrase / per_phrase_end_drop_db
      dropped at any depth, long_pauses / eaten_words / rushed_runs /
      low_conf_words capped to CAP items at any depth).
    - transcript: only "text" and a pruned copy of "derived" are kept;
      "words" and "segments" are never included. transcript=None (or a
      falsy/missing text) yields transcript_text="" and transcript_derived=None.
    - comparison / speaker_context: passed through unchanged, or None.
    """
    pruned_metrics = _prune(copy.deepcopy(metrics))

    transcript_text = ""
    transcript_derived = None
    if transcript:
        transcript_text = transcript.get("text") or ""
        derived = transcript.get("derived")
        if derived is not None:
            transcript_derived = _prune(copy.deepcopy(derived))

    return {
        "metrics": pruned_metrics,
        "transcript_text": transcript_text,
        "transcript_derived": transcript_derived,
        "comparison": comparison or None,
        "speaker_context": speaker_context or None,
    }
