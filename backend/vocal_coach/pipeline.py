"""One analysis job end to end: extract → analyse → transcribe → (coach) → store.

Runs inside a job worker. Computes `Tracks` once and shares it between analysis and
transcription so both see identical samples. Dedupe: if this user already has an analysis
for the same WAV bytes, config and analyser version, return it without re-analysing.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import parselmouth
from sqlalchemy.orm import Session

from vocal_coach.analysis.analyser import ANALYSER_VERSION, analyse_wav
from vocal_coach.analysis.audio import extract_wav
from vocal_coach.analysis.schema import SourceInfo
from vocal_coach.analysis.serialise import to_canonical_json
from vocal_coach.analysis.tracks import extract_tracks
from vocal_coach.config import AppConfig, config_hash
from vocal_coach.settings import Settings
from vocal_coach.storage import repo
from vocal_coach.transcription.run import transcribe_file
from vocal_coach.transcription.transcriber import WhisperLike, get_model

log = logging.getLogger(__name__)

STAGES = ("download", "extract", "analyse", "transcribe", "coach", "done")
STAGE_PROGRESS = {"download": 5, "extract": 20, "analyse": 55, "transcribe": 85, "coach": 90, "done": 100}
WORK_SUBDIR = "work"  # DATA_DIR/work/<job_id>/ holds the extracted WAV for the job's lifetime

Progress = Callable[[str, int], None]


@dataclass
class JobRequest:
    job_id: uuid.UUID
    user_id: uuid.UUID
    source_path: Path
    file_name: str
    recorded_at: datetime
    drive_file_id: str | None = None
    drive_modified_time: str | None = None
    speaker_context: str | None = None
    llm_enabled: bool = False
    llm_model: str | None = None


def _as_dict(model) -> dict:
    return json.loads(to_canonical_json(model))


def run_pipeline(
    req: JobRequest, cfg: AppConfig, settings: Settings, session: Session, progress: Progress,
    *, whisper_model: WhisperLike | None = None,
) -> uuid.UUID:
    work = settings.data_dir / WORK_SUBDIR / str(req.job_id)
    work.mkdir(parents=True, exist_ok=True)
    try:
        progress("download", STAGE_PROGRESS["download"])  # source is already local (upload); Drive arrives in Plan 7
        wav = work / (Path(req.file_name).stem + ".wav")
        try:
            info = extract_wav(req.source_path, wav)
        except (subprocess.CalledProcessError, ValueError) as e:  # not audio, truncated, or no audio stream
            raise RuntimeError(f"ffmpeg could not decode {req.file_name}: {e}") from e
        progress("extract", STAGE_PROGRESS["extract"])

        existing = repo.find_analysis(session, req.user_id, info.content_sha256, config_hash(cfg), ANALYSER_VERSION)
        if existing is not None:
            progress("done", STAGE_PROGRESS["done"])
            return existing.id

        tracks = extract_tracks(parselmouth.Sound(str(wav)), cfg.analysis)
        source = SourceInfo(
            file_name=req.file_name, drive_file_id=req.drive_file_id, drive_modified_time=req.drive_modified_time,
            content_sha256=info.content_sha256, duration_s=info.duration_s,
            original_channels=info.original_channels, original_sample_rate=info.original_sample_rate,
        )
        report = analyse_wav(wav, cfg, source, tracks=tracks)
        progress("analyse", STAGE_PROGRESS["analyse"])

        transcript_json: dict | None
        try:
            model = whisper_model if whisper_model is not None else get_model(cfg.transcription)
            transcript_json = _as_dict(transcribe_file(wav, cfg, model=model, tracks=tracks))
        except Exception:  # spec §15: transcription failure degrades, it does not fail the job
            log.exception("transcription failed for job %s; storing analysis without transcript", req.job_id)
            transcript_json = None
        progress("transcribe", STAGE_PROGRESS["transcribe"])

        progress("coach", STAGE_PROGRESS["coach"])  # LLM coaching lands in Plan 6

        row = repo.create_analysis(
            session, req.user_id, file_name=req.file_name, drive_file_id=req.drive_file_id,
            content_sha256=info.content_sha256, recorded_at=req.recorded_at,
            analyser_version=report.analyser_version, config_hash=report.config_hash,
            metrics_json=_as_dict(report), transcript_json=transcript_json, speaker_context=req.speaker_context,
        )
        progress("done", STAGE_PROGRESS["done"])
        return row.id
    finally:
        shutil.rmtree(work, ignore_errors=True)
