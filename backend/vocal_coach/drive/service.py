"""Wires the Drive package into the product: connection lifecycle, per-request access tokens,
and file listing. This is the only `vocal_coach.drive` module the API and the pipeline import."""
from __future__ import annotations

import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from vocal_coach.drive import cache, crypto, oauth
from vocal_coach.drive import state as oauth_state
from vocal_coach.drive.client import DriveClient, DriveFile
from vocal_coach.drive.errors import DriveError, DriveNotConfigured, DriveNotConnected
from vocal_coach.settings import Settings
from vocal_coach.storage import repo

NOT_CONFIGURED = "drive is not configured on this server"
DEFAULT_SECRET_KEY = "dev-secret-change-me"
MIN_SECRET_KEY_CHARS = 32


def require_configured(settings: Settings) -> None:
    if not settings.drive_configured:
        raise DriveNotConfigured(NOT_CONFIGURED)


def check_drive_settings(settings: Settings) -> None:
    """Startup guard: with Drive configured, refuse a guessable `SECRET_KEY` (it signs the OAuth
    state) and a `DRIVE_TOKEN_KEY` that is not a Fernet key. Messages never echo either value."""
    if not settings.drive_configured:
        return
    secret = settings.secret_key or ""
    if not secret or secret == DEFAULT_SECRET_KEY or len(secret) < MIN_SECRET_KEY_CHARS:
        raise RuntimeError(
            f"SECRET_KEY must be set to a random value of at least {MIN_SECRET_KEY_CHARS} characters "
            "when Google Drive is configured")
    try:
        Fernet(settings.drive_token_key.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("DRIVE_TOKEN_KEY is not a valid Fernet key") from exc


def start_connect(settings: Settings, user_id: uuid.UUID) -> tuple[str, str]:
    """Returns `(consent_url, nonce)`; the caller sets the nonce as the browser-binding cookie."""
    require_configured(settings)
    nonce = oauth_state.new_nonce()
    state = oauth_state.sign_state(settings.secret_key, user_id, nonce)
    return oauth.consent_url(settings, state), nonce


def verify_callback_state(settings: Settings, state: str) -> tuple[uuid.UUID, str]:
    """`(user_id, nonce)` from a signed state; raises `DriveStateError` when it does not verify."""
    return oauth_state.verify_state(settings.secret_key, state)


def complete_connect(session: Session, settings: Settings, *, code: str, user_id: uuid.UUID) -> None:
    """Exchanges the code and stores the connection for `user_id` (taken from an already verified
    state). A previous connection's refresh token is revoked first, best effort."""
    require_configured(settings)
    exchange = oauth.exchange_code(settings, code)
    previous = repo.get_drive_connection(session, user_id)
    if previous is not None:
        _revoke_stored(settings, previous.encrypted_refresh_token)
    encrypted = crypto.encrypt_token(settings.drive_token_key, exchange.refresh_token)
    repo.upsert_drive_connection(session, user_id, encrypted_refresh_token=encrypted, google_email=exchange.email)


def _revoke_stored(settings: Settings, blob: bytes) -> None:
    """Best effort: no key, or an unreadable token, just skips the revoke."""
    if not settings.drive_token_key:
        return
    try:
        token = crypto.decrypt_token(settings.drive_token_key, blob)
    except DriveError:
        return
    oauth.revoke(token)  # never raises


def disconnect(session: Session, settings: Settings, user_id: uuid.UUID) -> bool:
    row = repo.get_drive_connection(session, user_id)
    if row is None:
        return False
    _revoke_stored(settings, row.encrypted_refresh_token)
    repo.delete_drive_connection(session, user_id)
    return True


def access_token_for(session: Session, settings: Settings, user_id: uuid.UUID) -> str:
    require_configured(settings)
    row = repo.get_drive_connection(session, user_id)
    if row is None:
        raise DriveNotConnected("drive_not_connected")
    refresh_token = crypto.decrypt_token(settings.drive_token_key, row.encrypted_refresh_token)
    try:
        return oauth.refresh_access_token(settings, refresh_token)
    except DriveNotConnected:
        repo.delete_drive_connection(session, user_id)
        raise


def list_files(
    session: Session, settings: Settings, user_id: uuid.UUID, folder_id: str | None, *,
    include_folders: bool = False,
) -> list[DriveFile]:
    require_configured(settings)
    access_token = access_token_for(session, settings, user_id)
    return DriveClient(access_token).list_media(folder_id, include_folders=include_folders)


def connection_status(session: Session, user_id: uuid.UUID) -> tuple[bool, str | None]:
    row = repo.get_drive_connection(session, user_id)
    if row is None:
        return False, None
    return True, row.google_email


def download_for_job(
    session: Session, settings: Settings, user_id: uuid.UUID, file_id: str, modified_time: str, dest: Path,
) -> Path:
    """Downloads a Drive file into the job's cache path, unless it is already cached (a concurrent
    job for the same file id + modifiedTime already wrote it). Called from inside the worker, with
    its own session/settings. Any `DriveError` subclass propagates for the pipeline to translate
    into a user-facing message, including `DriveError("drive file too large")` past `DRIVE_MAX_MB`.

    Before downloading, evicts least-recently-used cache files (across all users) down to
    `CACHE_MAX_MB`, protecting `dest` so a cap already at or over the limit never blocks this job's
    own download."""
    if cache.is_cached(dest):
        return dest
    cache.prune_lru(settings.data_dir, max_bytes=settings.cache_max_bytes, protect=frozenset({dest}))
    token = access_token_for(session, settings, user_id)
    DriveClient(token).download(file_id, dest, max_bytes=settings.drive_max_bytes)
    return dest
