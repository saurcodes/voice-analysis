"""Tests for the Drive HTTP client: listing with paging and media filter, get_file,
and streamed, atomic download. No network; every request is mocked via pytest-httpx."""
from __future__ import annotations

import os

import httpx
import pytest
from pytest_httpx import IteratorStream

from vocal_coach.drive.client import DRIVE_API, MEDIA_EXTENSIONS, DriveClient, DriveFile
from vocal_coach.drive.errors import DriveError, DriveNotConnected, DriveNotFound

TOKEN = "fake-access-token"


def _client() -> DriveClient:
    return DriveClient(TOKEN)


def _file_json(id_, name, mime_type="audio/mp4", modified_time="2026-10-04T10:42:00.000Z", size="123"):
    return {"id": id_, "name": name, "mimeType": mime_type, "modifiedTime": modified_time, "size": size}


def test_list_media_filters_folders_and_docs_and_sorts_by_name(httpx_mock):
    httpx_mock.add_response(
        url=httpx.URL(DRIVE_API, params={
            "q": "'root' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size)",
            "pageSize": 200,
        }),
        json={
            "files": [
                _file_json("1", "zebra.mp3"),
                _file_json("2", "Folder", mime_type="application/vnd.google-apps.folder"),
                _file_json("3", "doc.gdoc", mime_type="application/vnd.google-apps.document"),
                _file_json("4", "alpha.wav"),
                _file_json("5", "notes.pdf", mime_type="application/pdf"),
            ]
        },
    )

    files = _client().list_media(None)

    assert [f.name for f in files] == ["alpha.wav", "zebra.mp3"]
    assert all(isinstance(f, DriveFile) for f in files)
    assert files[0].ext == "wav"
    assert files[0].size == 123


def test_list_media_follows_next_page_token(httpx_mock):
    httpx_mock.add_response(
        url=httpx.URL(DRIVE_API, params={
            "q": "'folder-1' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size)",
            "pageSize": 200,
        }),
        json={"nextPageToken": "page-2", "files": [_file_json("1", "a.mp3")]},
    )
    httpx_mock.add_response(
        url=httpx.URL(DRIVE_API, params={
            "q": "'folder-1' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size)",
            "pageSize": 200,
            "pageToken": "page-2",
        }),
        json={"files": [_file_json("2", "b.mp3")]},
    )

    files = _client().list_media("folder-1")

    assert [f.name for f in files] == ["a.mp3", "b.mp3"]
    reqs = httpx_mock.get_requests()
    assert len(reqs) == 2
    assert "pageToken=page-2" in str(reqs[1].url)
    assert "pageToken" not in str(reqs[0].url)


def test_list_media_empty_folder_returns_empty_list(httpx_mock):
    httpx_mock.add_response(json={"files": []})

    assert _client().list_media("empty-folder") == []


def test_list_media_401_raises_drive_not_connected(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": "unauthorized"})

    with pytest.raises(DriveNotConnected, match="drive_not_connected"):
        _client().list_media(None)


def test_list_media_404_raises_drive_not_found(httpx_mock):
    httpx_mock.add_response(status_code=404, json={"error": "not found"})

    with pytest.raises(DriveNotFound, match="folder not found"):
        _client().list_media("missing-folder")


def test_list_media_rejects_folder_id_with_quote_without_request():
    with pytest.raises(DriveNotFound, match="folder not found"):
        _client().list_media("evil' or 1=1")


def test_list_media_other_error_raises_drive_error(httpx_mock):
    httpx_mock.add_response(status_code=500, text="internal error, token=secret")

    with pytest.raises(DriveError, match="google drive error 500") as exc_info:
        _client().list_media(None)
    assert "secret" not in str(exc_info.value)


def test_list_media_timeout_raises_drive_error(httpx_mock):
    httpx_mock.add_exception(httpx.ReadTimeout("t"))

    with pytest.raises(DriveError, match="google drive connection error"):
        _client().list_media(None)


def test_list_media_transport_error_raises_drive_error(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("boom"))

    with pytest.raises(DriveError, match="google drive connection error"):
        _client().list_media(None)


def test_get_file_returns_drive_file(httpx_mock):
    httpx_mock.add_response(
        url=httpx.URL(f"{DRIVE_API}/file-1", params={"fields": "id,name,mimeType,modifiedTime,size"}),
        json=_file_json("file-1", "take.m4a"),
    )

    result = _client().get_file("file-1")

    assert result == DriveFile(
        id="file-1", name="take.m4a", mime_type="audio/mp4",
        modified_time="2026-10-04T10:42:00.000Z", size=123,
    )


def test_get_file_404_raises_drive_not_found_with_file_id(httpx_mock):
    httpx_mock.add_response(status_code=404, json={"error": "not found"})

    with pytest.raises(DriveNotFound, match="drive file file-1 not found"):
        _client().get_file("file-1")


def test_get_file_401_raises_drive_not_connected(httpx_mock):
    httpx_mock.add_response(status_code=401)

    with pytest.raises(DriveNotConnected, match="drive_not_connected"):
        _client().get_file("file-1")


def test_get_file_size_missing_is_none(httpx_mock):
    body = _file_json("file-1", "take.m4a")
    del body["size"]
    httpx_mock.add_response(json=body)

    result = _client().get_file("file-1")

    assert result.size is None


def test_download_streams_chunks_and_writes_atomically(tmp_path, httpx_mock):
    dest = tmp_path / "out.mp3"
    chunks = [b"abc", b"def", b"ghi"]
    httpx_mock.add_response(
        url=f"{DRIVE_API}/file-1?alt=media",
        stream=IteratorStream(chunks),
    )

    result = _client().download("file-1", dest)

    assert result == dest
    assert dest.read_bytes() == b"abcdefghi"
    assert list(tmp_path.iterdir()) == [dest]


def test_download_creates_parent_dirs(tmp_path, httpx_mock):
    dest = tmp_path / "nested" / "dir" / "out.mp3"
    httpx_mock.add_response(url=f"{DRIVE_API}/file-1?alt=media", content=b"hello")

    result = _client().download("file-1", dest)

    assert result.read_bytes() == b"hello"


def test_download_404_raises_drive_not_found_and_leaves_no_partial_file(tmp_path, httpx_mock):
    dest = tmp_path / "out.mp3"
    httpx_mock.add_response(url=f"{DRIVE_API}/file-1?alt=media", status_code=404)

    with pytest.raises(DriveNotFound, match="drive file file-1 not found"):
        _client().download("file-1", dest)

    assert list(tmp_path.iterdir()) == []


def test_download_401_raises_drive_not_connected(tmp_path, httpx_mock):
    dest = tmp_path / "out.mp3"
    httpx_mock.add_response(url=f"{DRIVE_API}/file-1?alt=media", status_code=401)

    with pytest.raises(DriveNotConnected, match="drive_not_connected"):
        _client().download("file-1", dest)

    assert list(tmp_path.iterdir()) == []


def test_download_500_mid_stream_leaves_no_partial_file(tmp_path, httpx_mock):
    dest = tmp_path / "out.mp3"
    httpx_mock.add_response(url=f"{DRIVE_API}/file-1?alt=media", status_code=500)

    with pytest.raises(DriveError, match="google drive error 500"):
        _client().download("file-1", dest)

    assert list(tmp_path.iterdir()) == []


def test_download_connection_drop_mid_stream_leaves_no_partial_file(tmp_path, httpx_mock):
    dest = tmp_path / "out.mp3"

    def _broken_chunks():
        yield b"partial-bytes"
        raise httpx.ReadError("connection dropped")

    httpx_mock.add_response(url=f"{DRIVE_API}/file-1?alt=media", stream=IteratorStream(_broken_chunks()))

    with pytest.raises(DriveError, match="google drive connection error"):
        _client().download("file-1", dest)

    assert list(tmp_path.iterdir()) == []


def test_download_part_file_name_includes_pid(tmp_path, httpx_mock, monkeypatch):
    dest = tmp_path / "out.mp3"
    seen_names = []

    real_replace = os.replace

    def spy_replace(src, dst):
        seen_names.append(os.path.basename(src))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    httpx_mock.add_response(url=f"{DRIVE_API}/file-1?alt=media", content=b"data")

    _client().download("file-1", dest)

    assert seen_names == [f"out.mp3.{os.getpid()}.part"]


def test_media_extensions_constant():
    assert MEDIA_EXTENSIONS == frozenset({"m4a", "mp3", "wav", "mov", "mp4"})
