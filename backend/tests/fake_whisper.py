"""A stand-in for faster_whisper.WhisperModel that never loads weights.

Segments and words are the real faster-whisper dataclasses, so attribute drift in the
library breaks these tests instead of production.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from faster_whisper.transcribe import Segment, Word


def word(start: float, end: float, text: str, probability: float = 0.9) -> Word:
    return Word(start=start, end=end, word=text, probability=probability)


def seg(start: float, end: float, text: str, words: list[Word] | None,
        avg_logprob: float = -0.3, no_speech_prob: float = 0.02) -> Segment:
    return Segment(
        id=0, seek=0, start=start, end=end, text=text, tokens=[],
        avg_logprob=avg_logprob, compression_ratio=1.0, no_speech_prob=no_speech_prob,
        words=words, temperature=0.0,
    )


class FakeWhisper:
    def __init__(self, segments: list[Segment], language: str | None = "en"):
        self._segments = segments
        self._language = language
        self.calls: list[dict] = []
        self.audio: list[np.ndarray] = []

    def transcribe(self, audio: np.ndarray, **kwargs):
        self.audio.append(audio)
        self.calls.append(kwargs)
        return iter(self._segments), SimpleNamespace(language=self._language)
