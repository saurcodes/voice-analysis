"""faster-whisper wrapper with fixed decoding settings and an injectable model."""
from __future__ import annotations

import threading
from typing import Any, Iterable, NamedTuple, Protocol

import numpy as np

from vocal_coach.config import TranscriptionConfig
from vocal_coach.transcription.schema import TranscriptSegment, TranscriptWord

DECODE_TEMPERATURE = 0.0  # greedy/beam decoding only: no sampling, for repeatable output
DEVICE = "cpu"  # CPU-only in this environment; GPU selection is a later-plan concern
WHISPER_SAMPLE_RATE = 16000  # faster-whisper expects 16 kHz mono float32
CONDITION_ON_PREVIOUS_TEXT = False  # with temperature fixed at 0 there is no fallback to break repetition loops; do not feed the previous window's text as prompt


class WhisperLike(Protocol):
    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> tuple[Iterable[Any], Any]: ...


class RawTranscription(NamedTuple):
    language: str | None
    segments: list[TranscriptSegment]
    words: list[TranscriptWord]
    text: str


_MODEL_CACHE: dict[tuple[str, str], WhisperLike] = {}
_MODEL_LOCK = threading.Lock()


def load_model(cfg: TranscriptionConfig) -> WhisperLike:
    from faster_whisper import WhisperModel  # imported lazily: heavy, and tests never need it

    return WhisperModel(cfg.model_size, device=DEVICE, compute_type=cfg.compute_type)


def get_model(cfg: TranscriptionConfig) -> WhisperLike:
    """Load the model once per (size, compute type) per process; thread-safe."""
    key = (cfg.model_size, cfg.compute_type)
    with _MODEL_LOCK:
        if key not in _MODEL_CACHE:
            _MODEL_CACHE[key] = load_model(cfg)
        return _MODEL_CACHE[key]


def transcribe_audio(audio: np.ndarray, sample_rate: int, cfg: TranscriptionConfig, model: WhisperLike) -> RawTranscription:
    """Transcribe already-decoded mono samples (whisper's own file decoder is not used)."""
    if sample_rate != WHISPER_SAMPLE_RATE:
        raise ValueError(f"whisper needs {WHISPER_SAMPLE_RATE} Hz mono audio, got {sample_rate} Hz")
    segments_iter, info = model.transcribe(
        np.asarray(audio, dtype=np.float32),
        beam_size=cfg.beam_size,
        temperature=DECODE_TEMPERATURE,
        word_timestamps=True,
        vad_filter=False,
        language=cfg.language,
        condition_on_previous_text=CONDITION_ON_PREVIOUS_TEXT,
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
