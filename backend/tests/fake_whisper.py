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
