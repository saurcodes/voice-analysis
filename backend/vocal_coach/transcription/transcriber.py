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
