"""Run every analysis module on a WAV and assemble a MetricsReport. Also a CLI."""
from __future__ import annotations

import argparse
from pathlib import Path

import parselmouth

from vocal_coach.analysis import (
    articulation, energy, intonation, pace, phrasing, pitch, quality, timeline, voice_quality,
)
from vocal_coach.analysis.articulation import ArticulationBlock, VowelSpace
from vocal_coach.analysis.audio import extract_wav
from vocal_coach.analysis.energy import EnergyBlock
from vocal_coach.analysis.intonation import IntonationBlock
from vocal_coach.analysis.pace import PaceBlock
from vocal_coach.analysis.phrasing import PhrasingBlock
from vocal_coach.analysis.pitch import PitchBlock
from vocal_coach.analysis.quality import RecordingQualityBlock
from vocal_coach.analysis.schema import SCHEMA_VERSION, MetricsReport, SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.timeline import TimelineBlock
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.analysis.voice_quality import VoiceQualityBlock
from vocal_coach.config import AppConfig, config_hash, load_config

ANALYSER_VERSION = "0.1.0"


def _empty_report(source: SourceInfo, cfg: AppConfig) -> MetricsReport:
    """Report for audio too short to analyse (spec section 10): every metric null or zero."""
    return MetricsReport(
        schema_version=SCHEMA_VERSION,
        analyser_version=ANALYSER_VERSION,
        config_hash=config_hash(cfg),
        source=source,
        recording_quality=RecordingQualityBlock(
            noise_floor_db=None, snr_estimate_db=None, low_confidence=True, reasons=["too_short"],
        ),
        pitch=PitchBlock(
            f0_median_hz=None, f0_p10_hz=None, f0_p90_hz=None, f0_range_st=None,
            voiced_fraction=0.0, creak_fraction_below_100hz=None,
            opening_f0_median_hz=None, opening_vs_overall_st=None,
        ),
        phrasing=PhrasingBlock(
            phrase_count=0, speaking_time_s=0.0, mean_phrase_length_s=None, pause_count=0,
            pauses_per_min=0.0, mean_pause_length_s=None, long_pause_count_ge_1s=0, long_pauses=[],
        ),
        pace=PaceBlock(syllable_count_est=0, syllables_per_sec_overall=0.0, articulation_rate_syl_per_sec=None),
        intonation=IntonationBlock(
            up_count=0, down_count=0, flat_count=0, unclassified_count=0, flat_pct=None, per_phrase=[],
        ),
        energy=EnergyBlock(
            body_median_db=None, final_15s_median_db=None, final_vs_body_db=None,
            trailing_off_count=0, per_phrase_end_drop_db=[],
        ),
        voice_quality=VoiceQualityBlock(hnr_db=None, jitter_local=None, shimmer_local=None, low_confidence=True),
        articulation=ArticulationBlock(
            hf_energy_ratio_db=None, spectral_tilt_db_per_oct=None, modulation_depth=None,
            syllable_peak_prominence_mean_db=None, syllable_peak_prominence_p25_db=None,
            weak_peak_fraction=None,
            vowel_space=VowelSpace(
                f1_sd_hz=None, f2_sd_hz=None, vowel_space_area_hz2=None, vowel_dispersion_st=None,
            ),
            low_confidence=True,
        ),
        timeline=TimelineBlock(window_s=cfg.analysis.energy_window_s, windows=[]),
    )


def analyse_wav(wav_path: Path, cfg: AppConfig, source: SourceInfo) -> MetricsReport:
    sound = parselmouth.Sound(str(wav_path))
    if sound.get_total_duration() < cfg.analysis.min_duration_s:
        return _empty_report(source, cfg)
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
