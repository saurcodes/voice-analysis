"""Per-user cache of Google Drive downloads, named by file id and `modifiedTime` so
a changed file in Drive re-downloads on next use. The derived 16 kHz WAV is not
kept here; the pipeline derives it per job in its own temp work dir."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from vocal_coach.drive.client import DriveClient, DriveFile
from vocal_coach.storage.paths import cache_dir

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_DEFAULT_EXT = "bin"


def sanitise(value: str) -> str:
    return _UNSAFE_RE.sub("-", value)


def cache_path(data_dir: Path, user_id: uuid.UUID, file: DriveFile) -> Path:
    ext = file.ext or _DEFAULT_EXT
    return cache_dir(data_dir, user_id) / f"{file.id}__{sanitise(file.modified_time)}.{ext}"


def ensure_cached(
    data_dir: Path, user_id: uuid.UUID, file: DriveFile, client: DriveClient
) -> tuple[Path, bool]:
    path = cache_path(data_dir, user_id, file)
    if path.exists() and path.stat().st_size > 0:
        return path, False
    client.download(file.id, path)
    return path, True
