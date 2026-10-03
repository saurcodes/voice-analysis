"""Normalise any audio/video file to mono 16 kHz 16-bit WAV using ffmpeg."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

TARGET_SR = 16000


class AudioInfo(BaseModel):
    original_channels: int
    original_sample_rate: int
    duration_s: float
    content_sha256: str


def check_ffmpeg() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise RuntimeError(f"Required binaries not found on PATH: {', '.join(missing)}. Install ffmpeg.")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=channels,sample_rate", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    streams = json.loads(out).get("streams", [])
    if not streams:
        raise ValueError(f"No audio stream found in {path}")
    s = streams[0]
    return int(s["channels"]), int(s["sample_rate"])


def _duration_s(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def extract_wav(src: Path, dst: Path) -> AudioInfo:
    check_ffmpeg()
    channels, sample_rate = _probe(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1",
         "-ar", str(TARGET_SR), "-sample_fmt", "s16", "-f", "wav", str(dst)],
        check=True,
    )
    return AudioInfo(
        original_channels=channels,
        original_sample_rate=sample_rate,
        duration_s=_duration_s(dst),
        content_sha256=sha256_file(dst),
    )
