"""Tests for the per-user Drive download cache: path naming/sanitising, the cache-hit
predicate (a zero-byte stale file is a miss), `download_for_job` (the single place that
downloads into the cache, pruning LRU first and capping the download size), and the
LRU prune / per-file removal functions behind the cache size cap and delete cleanup.
No network."""
from __future__ import annotations

import os
from pathlib import Path

import uuid

import pytest

from vocal_coach.drive import service
from vocal_coach.drive.cache import cache_path, is_cached, prune_lru, remove_for_file, sanitise
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
            assert max_bytes == settings.drive_max_bytes
            assert not calls  # a second real download would mean the cache check was skipped
            calls.append(file_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"downloaded once")
            return dest

    settings = Settings(_env_file=None, max_upload_mb=3, data_dir=tmp_path)
    monkeypatch.setattr(service, "access_token_for", lambda *a, **k: "tok")
    monkeypatch.setattr(service, "DriveClient", FakeClient)

    dest = tmp_path / "cache" / str(USER_ID) / "file-1__mt.m4a"

    first = service.download_for_job(None, settings, USER_ID, "file-1", "2026-10-04T10:42:00.000Z", dest)
    second = service.download_for_job(None, settings, USER_ID, "file-1", "2026-10-04T10:42:00.000Z", dest)

    assert first == dest and second == dest
    assert calls == ["file-1"]
    assert dest.read_bytes() == b"downloaded once"


def test_download_for_job_uses_drive_max_bytes_override(tmp_path, monkeypatch):
    calls: list[int | None] = []

    class FakeClient:
        def __init__(self, token):
            pass

        def download(self, file_id, dest, *, max_bytes=None):
            calls.append(max_bytes)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x")
            return dest

    settings = Settings(_env_file=None, max_upload_mb=500, drive_max_mb=10, data_dir=tmp_path)
    monkeypatch.setattr(service, "access_token_for", lambda *a, **k: "tok")
    monkeypatch.setattr(service, "DriveClient", FakeClient)

    dest = tmp_path / "cache" / str(USER_ID) / "file-9__mt.m4a"
    service.download_for_job(None, settings, USER_ID, "file-9", "2026-10-04T10:42:00.000Z", dest)

    assert calls == [10 * 1024 * 1024]


def test_download_for_job_prunes_the_cache_before_downloading_protecting_the_destination(tmp_path, monkeypatch):
    """Review Focus 4: the cache is already over a 1 MB cap from another user's old files; the
    current job's destination is protected throughout, the oldest file is evicted to make room, and
    afterwards the cache is over the cap by at most the one new download."""
    other_user = uuid.uuid4()
    stale_dir = tmp_path / "cache" / str(other_user)
    oldest = stale_dir / "old__mt.wav"
    newer = stale_dir / "newer__mt.wav"
    _touch(oldest, size=600 * 1024, mtime=1_000)
    _touch(newer, size=600 * 1024, mtime=2_000)
    downloaded = b"1" * 5

    class FakeClient:
        def __init__(self, token):
            pass

        def download(self, file_id, dest, *, max_bytes=None):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(downloaded)
            return dest

    settings = Settings(_env_file=None, cache_max_mb=1, data_dir=tmp_path)
    monkeypatch.setattr(service, "access_token_for", lambda *a, **k: "tok")
    monkeypatch.setattr(service, "DriveClient", FakeClient)

    dest = tmp_path / "cache" / str(USER_ID) / "new__mt.wav"
    result = service.download_for_job(None, settings, USER_ID, "new", "2026-10-04T10:42:00.000Z", dest)

    assert result == dest
    assert dest.read_bytes() == downloaded
    assert not oldest.exists()  # evicted to make room
    assert newer.exists()  # one eviction already got under the cap
    total = sum(p.stat().st_size for p in (tmp_path / "cache").rglob("*") if p.is_file())
    assert total <= settings.cache_max_bytes + len(downloaded)


def _touch(path: Path, *, size: int, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)
    os.utime(path, (mtime, mtime))


def test_prune_lru_evicts_oldest_first_until_under_the_cap(tmp_path):
    oldest = tmp_path / "cache" / "u1" / "a__mt.wav"
    middle = tmp_path / "cache" / "u1" / "b__mt.wav"
    newest = tmp_path / "cache" / "u2" / "c__mt.wav"
    _touch(oldest, size=10, mtime=1)
    _touch(middle, size=10, mtime=2)
    _touch(newest, size=10, mtime=3)

    removed = prune_lru(tmp_path, max_bytes=15)  # 30 bytes total; removing the oldest two gets to 10

    assert removed == [oldest, middle]
    assert not oldest.exists()
    assert not middle.exists()
    assert newest.exists()


def test_prune_lru_never_touches_part_files(tmp_path):
    part = tmp_path / "cache" / "u1" / "a__mt.wav.1234.part"
    _touch(part, size=1000, mtime=1)

    removed = prune_lru(tmp_path, max_bytes=0)

    assert removed == []
    assert part.exists()


def test_prune_lru_never_touches_protected_paths_even_when_cap_already_exceeded(tmp_path):
    """Review Focus 4: a protected destination survives pruning even though the cache (counting
    only unprotected files) is already over the cap before this download starts."""
    protected = tmp_path / "cache" / "u1" / "keep__mt.wav"
    evictable = tmp_path / "cache" / "u1" / "evict__mt.wav"
    _touch(protected, size=1000, mtime=1)  # oldest, but protected
    _touch(evictable, size=10, mtime=2)

    removed = prune_lru(tmp_path, max_bytes=0, protect=frozenset({protected}))

    assert removed == [evictable]
    assert protected.exists()
    assert not evictable.exists()


def test_prune_lru_returns_empty_list_when_nothing_to_remove(tmp_path):
    kept = tmp_path / "cache" / "u1" / "a__mt.wav"
    _touch(kept, size=10, mtime=1)

    assert prune_lru(tmp_path, max_bytes=100) == []
    assert kept.exists()


def test_prune_lru_on_missing_cache_dir_returns_empty_list(tmp_path):
    assert prune_lru(tmp_path, max_bytes=0) == []


def test_prune_lru_never_raises_when_a_file_vanishes_concurrently(tmp_path, monkeypatch):
    stubborn = tmp_path / "cache" / "u1" / "a__mt.wav"
    removable = tmp_path / "cache" / "u1" / "b__mt.wav"
    _touch(stubborn, size=10, mtime=1)
    _touch(removable, size=10, mtime=2)

    real_unlink = Path.unlink

    def flaky_unlink(self, *a, **k):
        if self == stubborn:
            raise OSError("vanished concurrently")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    removed = prune_lru(tmp_path, max_bytes=0)

    assert removed == [removable]
    assert stubborn.exists()  # the failed unlink left it behind, no exception raised
    assert not removable.exists()


def test_remove_for_file_removes_every_cached_copy_for_that_user_only(tmp_path):
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    target1 = cache_path(tmp_path, user_a, _file(id_="f1", modified_time="2026-10-01T00:00:00.000Z"))
    target2 = cache_path(tmp_path, user_a, _file(id_="f1", modified_time="2026-10-02T00:00:00.000Z"))
    other_file = cache_path(tmp_path, user_a, _file(id_="f2", modified_time="2026-10-01T00:00:00.000Z"))
    other_user = cache_path(tmp_path, user_b, _file(id_="f1", modified_time="2026-10-01T00:00:00.000Z"))
    for p in (target1, target2, other_file, other_user):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")

    removed = remove_for_file(tmp_path, user_a, "f1")

    assert set(removed) == {target1, target2}
    assert not target1.exists() and not target2.exists()
    assert other_file.exists() and other_user.exists()


def test_remove_for_file_leaves_an_in_flight_part_file_alone(tmp_path):
    cached = cache_path(tmp_path, USER_ID, _file(id_="f1", modified_time="2026-10-01T00:00:00.000Z"))
    part = cached.with_name(cached.name + ".part")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"x")
    part.write_bytes(b"y")

    removed = remove_for_file(tmp_path, USER_ID, "f1")

    assert removed == [cached]
    assert part.exists()


def test_remove_for_file_on_nothing_cached_returns_empty_list(tmp_path):
    assert remove_for_file(tmp_path, USER_ID, "never-cached") == []
