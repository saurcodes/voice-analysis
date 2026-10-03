"""transcript.json document model (spec §7.1)."""
from __future__ import annotations

from pydantic import BaseModel

TRANSCRIPT_SCHEMA_VERSION = "1.0"


class TranscriptWord(BaseModel):
    start_s: float
    end_s: float
    word: str
    probability: float


class TranscriptSegment(BaseModel):
    start_s: float
    end_s: float
    text: str
    avg_logprob: float
    no_speech_prob: float


class Span(BaseModel):
    start_s: float
    end_s: float
    text: str


class LowConfWord(BaseModel):
    start_s: float
    end_s: float
    word: str
    probability: float


class EatenWord(BaseModel):
    start_s: float
    end_s: float
    word: str
    drop_db: float


class ClarityBlock(BaseModel):
    low_conf_word_fraction: float | None
    low_conf_words: list[LowConfWord]
    word_final_drop_count: int
    word_final_drop_fraction: float | None
    eaten_words: list[EatenWord]
    rushed_word_fraction: float | None
    rushed_runs: list[Span]
    segment_avg_logprob_mean: float | None
    low_logprob_segment_fraction: float | None


class DerivedBlock(BaseModel):
    word_count: int
    words_per_min: float
    filler_counts: dict[str, int]
    filler_total: int
    fillers_per_min: float
    clarity: ClarityBlock


class Transcript(BaseModel):
    schema_version: str
    model: str
    language: str | None
    text: str
    segments: list[TranscriptSegment]
    words: list[TranscriptWord]
    derived: DerivedBlock
