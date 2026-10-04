"""Where uploaded source files live under DATA_DIR. The one place that knows the layout.

An upload is stored once per user under the hash of its bytes (`source_sha256`), so re-uploading the
same file reuses it. It is removed when no analysis and no unfinished job references that hash."""
from __future__ import annotations

import uuid
from pathlib import Path

UPLOADS_SUBDIR = "uploads"


def uploads_dir(data_dir: Path, user_id: uuid.UUID) -> Path:
    return Path(data_dir) / UPLOADS_SUBDIR / str(user_id)


def upload_path(data_dir: Path, user_id: uuid.UUID, source_sha256: str, ext: str) -> Path:
    return uploads_dir(data_dir, user_id) / f"{source_sha256}.{ext.lstrip('.')}"


def find_uploads(data_dir: Path, user_id: uuid.UUID, source_sha256: str) -> list[Path]:
    """Every stored copy of this upload, whatever its extension."""
    return sorted(uploads_dir(data_dir, user_id).glob(f"{source_sha256}.*"))


def find_upload(data_dir: Path, user_id: uuid.UUID, source_sha256: str) -> Path | None:
    return next(iter(find_uploads(data_dir, user_id, source_sha256)), None)


def remove_upload(data_dir: Path, user_id: uuid.UUID, source_sha256: str) -> list[Path]:
    removed = find_uploads(data_dir, user_id, source_sha256)
    for path in removed:
        path.unlink(missing_ok=True)
    return removed
