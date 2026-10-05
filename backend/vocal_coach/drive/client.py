"""Google Drive v3 HTTP client, over httpx (no Google SDK). Lists and downloads a
user's media files using a per-request access token (never stored here). Every
non-2xx response is mapped to a `DriveError` subclass carrying only a status
code or a fixed message; the response body, URL and token are never surfaced.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from vocal_coach.drive.errors import DriveError, DriveNotConnected, DriveNotFound

DRIVE_API = "https://www.googleapis.com/drive/v3/files"
PAGE_SIZE = 200
MAX_FILES = 1000
MEDIA_EXTENSIONS = frozenset({"m4a", "mp3", "wav", "mov", "mp4"})
_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_LIST_FIELDS = "nextPageToken,files(id,name,mimeType,modifiedTime,size)"
_GET_FIELDS = "id,name,mimeType,modifiedTime,size"
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, read=60.0)


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: str
    size: int | None

    @property
    def ext(self) -> str:
        suffix = Path(self.name).suffix
        return suffix[1:].lower() if suffix else ""


def _parse_size(raw: str | None) -> int | None:
    return int(raw) if raw is not None else None


def _file_from_json(data: dict) -> DriveFile:
    return DriveFile(
        id=data["id"],
        name=data["name"],
        mime_type=data["mimeType"],
        modified_time=data["modifiedTime"],
        size=_parse_size(data.get("size")),
    )


class DriveClient:
    def __init__(self, access_token: str, *, timeout: httpx.Timeout | float = _DEFAULT_TIMEOUT) -> None:
        self._access_token = access_token
        self._timeout = timeout

    def list_media(self, folder_id: str | None) -> list[DriveFile]:
        if folder_id is not None and "'" in folder_id:
            raise DriveNotFound("folder not found")
        parent = folder_id or "root"
        params = {
            "q": f"'{parent}' in parents and trashed = false",
            "fields": _LIST_FIELDS,
            "pageSize": PAGE_SIZE,
        }
        files: list[DriveFile] = []
        page_token: str | None = None
        with httpx.Client(timeout=self._timeout) as client:
            while True:
                request_params = dict(params)
                if page_token:
                    request_params["pageToken"] = page_token
                data = self._get(client, DRIVE_API, request_params, not_found="folder not found")
                for entry in data.get("files", []):
                    file = _file_from_json(entry)
                    if file.mime_type == _FOLDER_MIME_TYPE:
                        continue
                    if file.ext not in MEDIA_EXTENSIONS:
                        continue
                    files.append(file)
                    if len(files) >= MAX_FILES:
                        return sorted(files, key=lambda f: f.name.lower())
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return sorted(files, key=lambda f: f.name.lower())

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
        file is removed and `DriveError("drive file too large")` raised."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + f".{os.getpid()}.part")
        try:
            with httpx.Client(timeout=self._timeout) as client:
                try:
                    with client.stream(
                        "GET",
                        f"{DRIVE_API}/{file_id}",
                        params={"alt": "media"},
                        headers=self._headers(),
                    ) as response:
                        self._raise_for_status(response, not_found=f"drive file {file_id} not found")
                        written = 0
                        with open(part, "wb") as handle:
                            for chunk in response.iter_bytes():
                                written += len(chunk)
                                if max_bytes is not None and written > max_bytes:
                                    raise DriveError("drive file too large")
                                handle.write(chunk)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    raise DriveError("google drive connection error") from exc
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        os.replace(part, dest)
        return dest

    # -- internals -----------------------------------------------------------

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _get(self, client: httpx.Client, url: str, params: dict, *, not_found: str) -> dict:
        try:
            response = client.get(url, params=params, headers=self._headers())
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise DriveError("google drive connection error") from exc
        self._raise_for_status(response, not_found=not_found)
        try:
            return response.json()
        except ValueError as exc:  # never echo the body
            raise DriveError("google drive returned an invalid response") from exc

    def _raise_for_status(self, response: httpx.Response, *, not_found: str) -> None:
        if response.status_code == 401:
            raise DriveNotConnected("drive_not_connected")
        if response.status_code == 404:
            raise DriveNotFound(not_found)
        if not (200 <= response.status_code < 300):
            raise DriveError(f"google drive error {response.status_code}")
