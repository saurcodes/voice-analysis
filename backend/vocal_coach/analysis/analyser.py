"""Run every analysis module on a WAV and assemble a MetricsReport. Also a CLI."""
from __future__ import annotations

import argparse
from pathlib import Path

import parselmouth

from vocal_coach.analysis import (
    articulation, energy, intonation, pace, phrasing, pitch, quality, timeline, voice_quality,
)
from vocal_coach.analysis.audio import extract_wav
from vocal_coach.analysis.schema import SCHEMA_VERSION, MetricsReport, SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.config import AppConfig, config_hash, load_config

ANALYSER_VERSION = "0.1.0"


def analyse_wav(wav_path: Path, cfg: AppConfig, source: SourceInfo) -> MetricsReport:
    sound = parselmouth.Sound(str(wav_path))
    tracks = extract_tracks(sound, cfg.analysis)

    phr = phrasing.compute(tracks, cfg.analysis)
    rq = quality.compute(tracks, cfg.analysis, phr.phrases)
    pit = pitch.compute(tracks, cfg.analysis)
    pac = pace.compute(tracks, cfg.analysis, phr.block.speaking_time_s)
    into = intonation.compute(tracks, cfg.analysis, phr.phrases)
    ene = energy.compute(tracks, cfg.analysis, phr.phrases)
    vq = voice_quality.compute(tracks, cfg.analysis, rq.low_confidence)
    art = articulation.compute(
        tracks, cfg.analysis, cfg.articulation, phr.phrases,
        pac.peak_prominences_db, pit.f0_median_hz, rq.low_confidence,
    )
    tl = timeline.compute(tracks, cfg.analysis)

    return MetricsReport(
        schema_version=SCHEMA_VERSION,
        analyser_version=ANALYSER_VERSION,
        config_hash=config_hash(cfg),
        source=source,
        recording_quality=rq,
        pitch=pit,
        phrasing=phr.block,
        pace=pac.block,
        intonation=into,
        energy=ene,
        voice_quality=vq,
        articulation=art,
        timeline=tl,
    )


def analyse_file(
    src: Path,
    cfg: AppConfig,
    work_dir: Path,
    drive_file_id: str | None = None,
    drive_modified_time: str | None = None,
) -> MetricsReport:
    work_dir.mkdir(parents=True, exist_ok=True)
    wav = work_dir / (src.stem + ".wav")
    info = extract_wav(src, wav)
    source = SourceInfo(
        file_name=src.name,
        drive_file_id=drive_file_id,
        drive_modified_time=drive_modified_time,
        content_sha256=info.content_sha256,
        duration_s=info.duration_s,
        original_channels=info.original_channels,
        original_sample_rate=info.original_sample_rate,
    )
    return analyse_wav(wav, cfg, source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyse a recording and write metrics JSON.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="Output path (default: stdout)")
    parser.add_argument("--work-dir", type=Path, default=Path("data/work"))
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    report = analyse_file(args.file, cfg, args.work_dir)
    text = to_canonical_json(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
