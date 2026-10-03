"""Versioned metrics report schema."""
from __future__ import annotations

from pydantic import BaseModel

from vocal_coach.analysis.articulation import ArticulationBlock
from vocal_coach.analysis.energy import EnergyBlock
from vocal_coach.analysis.intonation import IntonationBlock
from vocal_coach.analysis.pace import PaceBlock
from vocal_coach.analysis.phrasing import PhrasingBlock
from vocal_coach.analysis.pitch import PitchBlock
from vocal_coach.analysis.quality import RecordingQualityBlock
from vocal_coach.analysis.timeline import TimelineBlock
from vocal_coach.analysis.voice_quality import VoiceQualityBlock

SCHEMA_VERSION = "1.0"


class SourceInfo(BaseModel):
    file_name: str
    drive_file_id: str | None
    drive_modified_time: str | None
    content_sha256: str
    duration_s: float
    original_channels: int
    original_sample_rate: int


class MetricsReport(BaseModel):
    schema_version: str
    analyser_version: str
    config_hash: str
    source: SourceInfo
    recording_quality: RecordingQualityBlock
    pitch: PitchBlock
    phrasing: PhrasingBlock
    pace: PaceBlock
    intonation: IntonationBlock
    energy: EnergyBlock
    voice_quality: VoiceQualityBlock
    articulation: ArticulationBlock
    timeline: TimelineBlock
