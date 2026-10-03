"""Assemble transcript.json from whisper output + intensity contour. Also a CLI."""
from __future__ import annotations

import argparse
from pathlib import Path

import parselmouth

from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.tracks import Tracks, extract_tracks
from vocal_coach.config import AppConfig, load_config
from vocal_coach.transcription import clarity
from vocal_coach.transcription.fillers import count_fillers, per_min, words_per_min
from vocal_coach.transcription.schema import TRANSCRIPT_SCHEMA_VERSION, DerivedBlock, Transcript
from vocal_coach.transcription.transcriber import RawTranscription, WhisperLike, get_model, transcribe_audio


def build_transcript(raw: RawTranscription, tracks: Tracks, duration_s: float, cfg: AppConfig) -> Transcript:
    filler_counts = count_fillers(raw.words, cfg.transcription.fillers)
    filler_total = sum(filler_counts.values())
    derived = DerivedBlock(
        word_count=len(raw.words),
        words_per_min=words_per_min(len(raw.words), duration_s),
        filler_counts=filler_counts,
        filler_total=filler_total,
        fillers_per_min=per_min(filler_total, duration_s),
        clarity=clarity.compute(raw.words, raw.segments, tracks, cfg.clarity),
    )
    return Transcript(
        schema_version=TRANSCRIPT_SCHEMA_VERSION,
        model=cfg.transcription.model_size,
        language=raw.language,
        text=raw.text,
        segments=raw.segments,
        words=raw.words,
        derived=derived,
    )


def transcribe_file(
    wav_path: Path,
    cfg: AppConfig,
    model: WhisperLike | None = None,
    tracks: Tracks | None = None,
) -> Transcript:
    """Transcribe a WAV and assemble the transcript document.

    `wav_path` is read only when `tracks` is not supplied; when `tracks` is given it must
    describe the same recording. `Tracks.samples` is channel 0 of the WAV; production audio
    is mono 16 kHz from `analysis.audio.extract_wav`.
    """
    if tracks is None:
        tracks = extract_tracks(parselmouth.Sound(str(wav_path)), cfg.analysis)
    model = model or get_model(cfg.transcription)
    raw = transcribe_audio(tracks.samples, tracks.sr, cfg.transcription, model)
    return build_transcript(raw, tracks, duration_s=tracks.duration_s, cfg=cfg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe a 16 kHz WAV and write transcript JSON.")
    parser.add_argument("wav", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="Output path (default: stdout)")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    text = to_canonical_json(transcribe_file(args.wav, cfg))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
