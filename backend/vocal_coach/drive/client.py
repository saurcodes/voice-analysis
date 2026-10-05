"""Google Drive v3 HTTP client, over httpx (no Google SDK). Lists and downloads a
user's media files using a per-request access token (never stored here). Every
non-2xx response is mapped to a `DriveError` subclass carrying only a status
code or a fixed message; the response body, URL and token are never surfaced.

Transient failures (a transport error, a timeout, HTTP 429, or a 5xx) are retried up to
`len(RETRY_DELAYS) + 1` times total, with `RETRY_DELAYS` between attempts; any other
failure (401, 404, or another 4xx) is never retried. For `download`, only the
request/response-headers phase is retried this way: once bytes have started streaming, a
failure propagates immediately (the existing part-file cleanup applies).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from vocal_coach.drive.errors import DriveError, DriveNotConnected, DriveNotFound

DRIVE_API = "https://www.googleapis.com/drive/v3/files"
PAGE_SIZE = 200
MAX_FILES = 1000
MEDIA_EXTENSIONS = frozenset({"m4a", "mp3", "wav", "mov", "mp4"})
RETRY_DELAYS = (0.5, 1.0)  # sleeps between attempts; len(RETRY_DELAYS) + 1 attempts total
_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_LIST_FIELDS = "nextPageToken,files(id,name,mimeType,modifiedTime,size)"
_GET_FIELDS = "id,name,mimeType,modifiedTime,size"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, read=60.0)
_MIN_RETRYABLE_STATUS = 500


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: str
    size: int | None
    is_folder: bool = False

    @property
    def ext(self) -> str:
        suffix = Path(self.name).suffix
        return suffix[1:].lower() if suffix else ""


class _Retryable(Exception):
    """Internal signal: wraps a transient failure so `_with_retry` knows it may retry. Never
    escapes `DriveClient`."""

    def __init__(self, error: DriveError) -> None:
        super().__init__(str(error))
        self.error = error


def _parse_size(raw: str | None) -> int | None:
    return int(raw) if raw is not None else None


def _file_from_json(data: dict) -> DriveFile:
    return DriveFile(
        id=data["id"],
        name=data["name"],
        mime_type=data["mimeType"],
        modified_time=data["modifiedTime"],
        size=_parse_size(data.get("size")),
        is_folder=data["mimeType"] == _FOLDER_MIME_TYPE,
    )


class DriveClient:
    def __init__(
        self, access_token: str, *, timeout: httpx.Timeout | float = _DEFAULT_TIMEOUT,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._access_token = access_token
        self._timeout = timeout
        self._sleep = sleep

    def list_media(self, folder_id: str | None, *, include_folders: bool = False) -> list[DriveFile]:
        if folder_id is not None and "'" in folder_id:
            raise DriveNotFound("folder not found")
        parent = folder_id or "root"
        params = {
            "q": f"'{parent}' in parents and trashed = false",
            "fields": _LIST_FIELDS,
            "pageSize": PAGE_SIZE,
        }
        files: list[DriveFile] = []
        folders: list[DriveFile] = []
        page_token: str | None = None
        with httpx.Client(timeout=self._timeout) as client:
            while True:
                request_params = dict(params)
                if page_token:
                    request_params["pageToken"] = page_token
                data = self._get(client, DRIVE_API, request_params, not_found="folder not found")
                for entry in data.get("files", []):
                    file = _file_from_json(entry)
                    if file.is_folder:
                        if include_folders:
                            folders.append(file)
                        continue
                    if file.ext not in MEDIA_EXTENSIONS:
                        continue
                    files.append(file)
                    if len(files) >= MAX_FILES:
                        return self._ordered(files, folders, include_folders)
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return self._ordered(files, folders, include_folders)

    @staticmethod
    def _ordered(files: list[DriveFile], folders: list[DriveFile], include_folders: bool) -> list[DriveFile]:
        sorted_files = sorted(files, key=lambda f: f.name.lower())
        if not include_folders:
            return sorted_files
        return sorted(folders, key=lambda f: f.name.lower()) + sorted_files

    def get_file(self, file_id: str) -> DriveFile:
        with httpx.Client(timeout=self._timeout) as client:
            data = self._get(
                client,
                f"{DRIVE_API}/{file_id}",
                {"fields": _GET_FIELDS},
                not_found=f"drive file {file_id} not found",
            )
        return _file_from_json(data)

    def download(self, file_id: str, dest: Path, *, max_bytes: int | None = None) -> Path:
        """Streams to a pid-named part file, then renames atomically. Over `max_bytes` the part
        file is removed and `DriveError("drive file too large")` raised. Connecting and receiving
        the response headers is retried like any other request; once chunks start arriving, a
        failure is not retried."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + f".{os.getpid()}.part")
        not_found = f"drive file {file_id} not found"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                stream_cm, response = self._with_retry(lambda: self._start_download(client, file_id, not_found))
                try:
                    written = 0
                    with open(part, "wb") as handle:
                        try:
                            for chunk in response.iter_bytes():
                                written += len(chunk)
                                if max_bytes is not None and written > max_bytes:
                                    raise DriveError("drive file too large")
                                handle.write(chunk)
                        except (httpx.TimeoutException, httpx.TransportError) as exc:
                            raise DriveError("google drive connection error") from exc
                finally:
                    stream_cm.__exit__(None, None, None)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        os.replace(part, dest)
        return dest

    def _start_download(self, client: httpx.Client, file_id: str, not_found: str):
        """One attempt at opening the download stream and checking its status: retryable failures
        (transport/timeout/429/5xx) raise `_Retryable`; anything else (401, 404, other 4xx) raises
        the final error directly. Returns `(stream_context_manager, response)` on success; the
        caller is responsible for exiting the context manager."""
        stream_cm = client.stream(
            "GET", f"{DRIVE_API}/{file_id}", params={"alt": "media"}, headers=self._headers(),
        )
        try:
            response = stream_cm.__enter__()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _Retryable(DriveError("google drive connection error")) from exc
        try:
            self._raise_for_status(response, not_found=not_found)
        except BaseException:
            stream_cm.__exit__(None, None, None)
            raise
        return stream_cm, response

    # -- internals -----------------------------------------------------------

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _with_retry(self, fn: Callable[[], object]) -> object:
        attempts = len(RETRY_DELAYS) + 1
        for attempt in range(attempts):
            try:
                return fn()
            except _Retryable as exc:
                if attempt == attempts - 1:
                    raise exc.error from None
                self._sleep(RETRY_DELAYS[attempt])
        raise AssertionError("unreachable")  # pragma: no cover

    def _get(self, client: httpx.Client, url: str, params: dict, *, not_found: str) -> dict:
        def attempt() -> dict:
            try:
                response = client.get(url, params=params, headers=self._headers())
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise _Retryable(DriveError("google drive connection error")) from exc
            self._raise_for_status(response, not_found=not_found)
            try:
                return response.json()
            except ValueError as exc:  # never echo the body
                raise DriveError("google drive returned an invalid response") from exc

        return self._with_retry(attempt)

    def _raise_for_status(self, response: httpx.Response, *, not_found: str) -> None:
        if response.status_code == 401:
            raise DriveNotConnected("drive_not_connected")
        if response.status_code == 404:
            raise DriveNotFound(not_found)
        if response.status_code == 429 or response.status_code >= _MIN_RETRYABLE_STATUS:
            raise _Retryable(DriveError(f"google drive error {response.status_code}"))
        if not (200 <= response.status_code < 300):
            raise DriveError(f"google drive error {response.status_code}")
