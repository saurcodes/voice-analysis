"""Tests for the per-user Drive download cache: path naming/sanitising, the cache-hit
predicate (a zero-byte stale file is a miss), and `download_for_job`, the single place
that downloads into the cache (with the upload size cap). No network."""
from __future__ import annotations

import uuid

import pytest

from vocal_coach.drive import service
from vocal_coach.drive.cache import cache_path, is_cached, sanitise
from vocal_coach.drive.client import DriveFile
from vocal_coach.settings import Settings

USER_ID = uuid.uuid4()


def _file(id_="file-1", name="take.m4a", modified_time="2026-10-04T10:42:00.000Z", size=5):
    return DriveFile(id=id_, name=name, mime_type="audio/mp4", modified_time=modified_time, size=size)


def test_sanitise_replaces_unsafe_characters():
    assert sanitise("2026-10-04T10:42:00.000Z") == "2026-10-04T10-42-00.000Z"


def test_sanitise_leaves_safe_characters_untouched():
    assert sanitise("abc-ABC_123.") == "abc-ABC_123."


def test_cache_path_layout_and_per_user_directory(tmp_path):
    file = _file()
    path = cache_path(tmp_path, USER_ID, file)

    assert path == tmp_path / "cache" / str(USER_ID) / "file-1__2026-10-04T10-42-00.000Z.m4a"


def test_cache_path_uses_bin_when_no_extension(tmp_path):
    file = _file(name="take-no-ext")
    path = cache_path(tmp_path, USER_ID, file)

    assert path.name == "file-1__2026-10-04T10-42-00.000Z.bin"


def test_is_cached_requires_a_non_empty_file(tmp_path):
    path = cache_path(tmp_path, USER_ID, _file())
    assert is_cached(path) is False
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    assert is_cached(path) is False  # a zero-byte leftover is a miss
    path.write_bytes(b"already here")
    assert is_cached(path) is True


def test_download_for_job_hit_after_first_download_never_calls_the_client_twice(tmp_path, monkeypatch):
    """Two jobs racing for the same cache key: the first downloads, the second finds it already
    there. `DriveClient.download` itself writes atomically (temp file + os.replace), so the only
    thing `download_for_job` must get right is re-checking existence before calling it at all."""
    calls: list[str] = []

    class FakeClient:
        def __init__(self, token):
            self.token = token

        def download(self, file_id, dest, *, max_bytes=None):
            assert max_bytes == settings.max_upload_bytes
            assert not calls  # a second real download would mean the cache check was skipped
            calls.append(file_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"downloaded once")
            return dest

    settings = Settings(_env_file=None, max_upload_mb=3)
    monkeypatch.setattr(service, "access_token_for", lambda *a, **k: "tok")
    monkeypatch.setattr(service, "DriveClient", FakeClient)

    dest = tmp_path / "cache" / str(USER_ID) / "file-1__mt.m4a"

    first = service.download_for_job(None, settings, USER_ID, "file-1", "2026-10-04T10:42:00.000Z", dest)
    second = service.download_for_job(None, settings, USER_ID, "file-1", "2026-10-04T10:42:00.000Z", dest)

    assert first == dest and second == dest
    assert calls == ["file-1"]
    assert dest.read_bytes() == b"downloaded once"
