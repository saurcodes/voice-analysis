"""Tests for the per-user Drive download cache: path naming/sanitising, cache hit
(no HTTP call), cache miss (downloads once), and a zero-byte stale file counting
as a miss. No network; the one real download in a miss goes through DriveClient,
mocked via pytest-httpx."""
from __future__ import annotations

import uuid

import pytest

from vocal_coach.drive import service
from vocal_coach.drive.cache import cache_path, ensure_cached, sanitise
from vocal_coach.drive.client import DRIVE_API, DriveClient, DriveFile

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


def test_ensure_cached_hit_returns_existing_path_without_request(tmp_path, httpx_mock):
    file = _file()
    path = cache_path(tmp_path, USER_ID, file)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"already here")
    client = DriveClient("token")

    result_path, downloaded = ensure_cached(tmp_path, USER_ID, file, client)

    assert result_path == path
    assert downloaded is False
    assert path.read_bytes() == b"already here"
    # httpx_mock's default assert_all_requests_were_expected means any unexpected
    # request (none registered here) would fail the test, confirming no call was made.


def test_ensure_cached_miss_downloads_once(tmp_path, httpx_mock):
    file = _file()
    httpx_mock.add_response(url=f"{DRIVE_API}/file-1?alt=media", content=b"downloaded bytes")
    client = DriveClient("token")

    result_path, downloaded = ensure_cached(tmp_path, USER_ID, file, client)

    assert downloaded is True
    assert result_path == cache_path(tmp_path, USER_ID, file)
    assert result_path.read_bytes() == b"downloaded bytes"
    assert len(httpx_mock.get_requests()) == 1


def test_ensure_cached_zero_byte_file_is_a_miss_and_redownloads(tmp_path, httpx_mock):
    file = _file()
    path = cache_path(tmp_path, USER_ID, file)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    httpx_mock.add_response(url=f"{DRIVE_API}/file-1?alt=media", content=b"fresh bytes")
    client = DriveClient("token")

    result_path, downloaded = ensure_cached(tmp_path, USER_ID, file, client)

    assert downloaded is True
    assert result_path.read_bytes() == b"fresh bytes"


def test_download_for_job_hit_after_first_download_never_calls_the_client_twice(tmp_path, monkeypatch):
    """Two jobs racing for the same cache key: the first downloads, the second finds it already
    there. `DriveClient.download` itself writes atomically (temp file + os.replace), so the only
    thing `download_for_job` must get right is re-checking existence before calling it at all."""
    calls: list[str] = []

    class FakeClient:
        def __init__(self, token):
            self.token = token

        def download(self, file_id, dest):
            assert not calls  # a second real download would mean the cache check was skipped
            calls.append(file_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"downloaded once")
            return dest

    monkeypatch.setattr(service, "access_token_for", lambda *a, **k: "tok")
    monkeypatch.setattr(service, "DriveClient", FakeClient)

    dest = tmp_path / "cache" / str(USER_ID) / "file-1__mt.m4a"

    first = service.download_for_job(None, None, USER_ID, "file-1", "2026-10-04T10:42:00.000Z", dest)
    second = service.download_for_job(None, None, USER_ID, "file-1", "2026-10-04T10:42:00.000Z", dest)

    assert first == dest and second == dest
    assert calls == ["file-1"]
    assert dest.read_bytes() == b"downloaded once"
