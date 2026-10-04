"""Pure payload builder: prunes and caps metrics/transcript for the LLM.

Operates on plain dicts (the stored JSON), never on pydantic objects. The
caller is responsible for loading metrics_json / transcript_json / comparison
from storage before calling build_payload.
"""
from __future__ import annotations

import copy
import statistics

CAP = 20

DEFAULT_MAX_TRANSCRIPT_WORDS = 1500

_TIMELINE_FIELDS = ("f0_median_hz", "f0_sd_st", "intensity_median_db")

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


def _stat(values: list[float]) -> dict:
    if not values:
        return {"min": None, "p50": None, "max": None}
    return {
        "min": round(min(values), 2),
        "p50": round(statistics.median(values), 2),
        "max": round(max(values), 2),
    }


def summarise_timeline(timeline: dict) -> dict:
    """Compact stand-in for metrics.timeline: window size, window count, and min / median / max of
    each per-window series over its non-null windows (all null gives null stats)."""
    windows = timeline.get("windows") or []
    summary: dict = {"window_s": timeline.get("window_s"), "window_count": len(windows)}
    for field in _TIMELINE_FIELDS:
        values = [w[field] for w in windows if isinstance(w, dict) and w.get(field) is not None]
        summary[field] = _stat(values)
    return summary


def build_payload(
    metrics: dict,
    transcript: dict | None,
    comparison: dict | None,
    speaker_context: str | None,
    *,
    max_transcript_words: int = DEFAULT_MAX_TRANSCRIPT_WORDS,
) -> dict:
    """Build the pruned payload sent to the LLM provider.

    - metrics: deep-copied then pruned (per_phrase / per_phrase_end_drop_db
      dropped at any depth, long_pauses / eaten_words / rushed_runs /
      low_conf_words capped to CAP items at any depth).
    - transcript: only "text" and a pruned copy of "derived" are kept;
      "words" and "segments" are never included. transcript=None (or a
      falsy/missing text) yields transcript_text="" and transcript_derived=None.
    - metrics.timeline (one entry per window, hundreds for a long recording) is replaced by
      metrics.timeline_summary (see summarise_timeline).
    - transcript text is capped at max_transcript_words words; transcript_truncated and
      transcript_word_count (the full count) are always present.
    - comparison / speaker_context: passed through unchanged, or None.
    """
    pruned_metrics = _prune(copy.deepcopy(metrics))
    if isinstance(pruned_metrics, dict) and "timeline" in pruned_metrics:
        timeline = pruned_metrics.pop("timeline")
        pruned_metrics["timeline_summary"] = summarise_timeline(timeline if isinstance(timeline, dict) else {})

    transcript_text = ""
    transcript_derived = None
    if transcript:
        transcript_text = transcript.get("text") or ""
        derived = transcript.get("derived")
        if derived is not None:
            transcript_derived = _prune(copy.deepcopy(derived))

    words = transcript_text.split()
    truncated = len(words) > max_transcript_words
    if truncated:
        transcript_text = " ".join(words[:max_transcript_words])

    return {
        "metrics": pruned_metrics,
        "transcript_text": transcript_text,
        "transcript_truncated": truncated,
        "transcript_word_count": len(words),
        "transcript_derived": transcript_derived,
        "comparison": comparison or None,
        "speaker_context": speaker_context or None,
    }
