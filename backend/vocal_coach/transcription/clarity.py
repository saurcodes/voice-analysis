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
