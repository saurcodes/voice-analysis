"""Per-user cache of Google Drive downloads, named by file id and `modifiedTime` so
a changed file in Drive re-downloads on next use. The derived 16 kHz WAV is not
kept here; the pipeline derives it per job in its own temp work dir.

The cache is capped in total size across all users (`CACHE_MAX_MB`/`settings.cache_max_bytes`),
evicted least-recently-used before each download (`prune_lru`); and a file's cached copies are
removed once no analysis references it any more (`remove_for_file`, called on delete)."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from vocal_coach.drive.client import DriveFile
from vocal_coach.storage.paths import CACHE_SUBDIR, cache_dir

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_DEFAULT_EXT = "bin"
_PART_SUFFIX = ".part"


def sanitise(value: str) -> str:
    return _UNSAFE_RE.sub("-", value)


def cache_path(data_dir: Path, user_id: uuid.UUID, file: DriveFile) -> Path:
    ext = file.ext or _DEFAULT_EXT
    return cache_dir(data_dir, user_id) / f"{file.id}__{sanitise(file.modified_time)}.{ext}"


def is_cached(path: Path) -> bool:
    """The one cache-hit check: a non-empty file at the cache path (a zero-byte leftover is a miss).
    Downloads go through `service.download_for_job`, which writes atomically."""
    return path.exists() and path.stat().st_size > 0


def prune_lru(data_dir: Path, *, max_bytes: int, protect: frozenset[Path] = frozenset()) -> list[Path]:
    """Evict cached Drive downloads, oldest (`st_mtime`) first, until the cache tree's total size
    (excluding `protect`) is at or under `max_bytes`. Walks every user's `cache/` directory under
    `data_dir`. A `.part` file (a download in progress) is never counted or removed, and nothing in
    `protect` (e.g. the destination of a download about to start) is ever counted or removed, even
    when the cache is already over the cap without it. A file that disappears between listing and
    unlinking (e.g. a concurrent cache hit or another prune) is skipped, never raised on.

    Returns the paths actually removed."""
    protect = {Path(p) for p in protect}
    root = Path(data_dir) / CACHE_SUBDIR
    if not root.exists():
        return []
    candidates: list[tuple[float, int, Path]] = []
    total = 0
    for path in root.rglob("*"):
        if path.name.endswith(_PART_SUFFIX) or not path.is_file() or path in protect:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        total += stat.st_size
        candidates.append((stat.st_mtime, stat.st_size, path))
    candidates.sort(key=lambda c: c[0])  # oldest first

    removed: list[Path] = []
    for _mtime, size, path in candidates:
        if total <= max_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        removed.append(path)
    return removed


def remove_for_file(data_dir: Path, user_id: uuid.UUID, file_id: str) -> list[Path]:
    """Deletes every cached copy of this Drive file for this user (one per `modifiedTime` it was
    ever cached under). Called once the last analysis referencing the file is deleted. Never raises
    on a file that is already gone."""
    removed: list[Path] = []
    for path in cache_dir(data_dir, user_id).glob(f"{file_id}__*"):
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed
