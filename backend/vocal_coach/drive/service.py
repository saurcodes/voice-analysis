"""Wires the Drive package into the product: connection lifecycle, per-request access tokens,
and file listing. This is the only `vocal_coach.drive` module the API and the pipeline import."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from vocal_coach.drive import crypto, oauth
from vocal_coach.drive import state as oauth_state
from vocal_coach.drive.client import DriveClient, DriveFile
from vocal_coach.drive.errors import DriveError, DriveNotConfigured, DriveNotConnected
from vocal_coach.settings import Settings
from vocal_coach.storage import repo

NOT_CONFIGURED = "drive is not configured on this server"


def require_configured(settings: Settings) -> None:
    if not settings.drive_configured:
        raise DriveNotConfigured(NOT_CONFIGURED)


def start_connect(settings: Settings, user_id: uuid.UUID) -> str:
    require_configured(settings)
    state = oauth_state.sign_state(settings.secret_key, user_id)
    return oauth.consent_url(settings, state)


def complete_connect(session: Session, settings: Settings, *, code: str, state: str) -> uuid.UUID:
    user_id = oauth_state.verify_state(settings.secret_key, state)
    require_configured(settings)
    exchange = oauth.exchange_code(settings, code)
    encrypted = crypto.encrypt_token(settings.drive_token_key, exchange.refresh_token)
    repo.upsert_drive_connection(session, user_id, encrypted_refresh_token=encrypted, google_email=exchange.email)
    return user_id


def disconnect(session: Session, settings: Settings, user_id: uuid.UUID) -> bool:
    row = repo.get_drive_connection(session, user_id)
    if row is None:
        return False
    try:
        token = crypto.decrypt_token(settings.drive_token_key, row.encrypted_refresh_token)
    except DriveError:
        token = None  # stored token is unreadable; still remove the row below
    if token is not None:
        oauth.revoke(token)  # best effort; never raises
    repo.delete_drive_connection(session, user_id)
    return True


def access_token_for(session: Session, settings: Settings, user_id: uuid.UUID) -> str:
    row = repo.get_drive_connection(session, user_id)
    if row is None:
        raise DriveNotConnected("drive_not_connected")
    refresh_token = crypto.decrypt_token(settings.drive_token_key, row.encrypted_refresh_token)
    try:
        return oauth.refresh_access_token(settings, refresh_token)
    except DriveNotConnected:
        repo.delete_drive_connection(session, user_id)
        raise


def list_files(session: Session, settings: Settings, user_id: uuid.UUID, folder_id: str | None) -> list[DriveFile]:
    require_configured(settings)
    access_token = access_token_for(session, settings, user_id)
    return DriveClient(access_token).list_media(folder_id)


def connection_status(session: Session, user_id: uuid.UUID) -> tuple[bool, str | None]:
    row = repo.get_drive_connection(session, user_id)
    if row is None:
        return False, None
    return True, row.google_email
