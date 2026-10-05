"""Google OAuth over httpx (no Google SDK): consent URL, code-for-token exchange, refresh, and
revoke. No token, client secret, or response body from Google is ever included in a log line or
in a message raised from here."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from vocal_coach.drive.errors import DriveError, DriveNotConnected
from vocal_coach.settings import Settings

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
SCOPES = (DRIVE_SCOPE, "https://www.googleapis.com/auth/userinfo.email")
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, read=30.0)
_CONNECTION_ERROR = "google token connection error"


@dataclass(frozen=True)
class TokenExchange:
    refresh_token: str
    access_token: str
    email: str | None


def consent_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _email_for(client: httpx.Client, access_token: str) -> str | None:
    """Best-effort email lookup: any failure (network, non-2xx, unparsable body) yields None, never
    a raised error, since the connection itself already succeeded by this point."""
    try:
        response = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if response.status_code != 200:
            return None
        return response.json().get("email")
    except (httpx.TimeoutException, httpx.TransportError, ValueError):
        return None


def exchange_code(settings: Settings, code: str) -> TokenExchange:
    form = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
        try:
            response = client.post(TOKEN_URL, data=form)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise DriveError(_CONNECTION_ERROR) from exc
        if not (200 <= response.status_code < 300):
            raise DriveError(f"google token error {response.status_code}")
        data = response.json()
        granted = data.get("scope")
        if isinstance(granted, str) and DRIVE_SCOPE not in granted.split():
            raise DriveError("drive access was not granted")
        refresh_token = data.get("refresh_token")
        if not refresh_token:
            raise DriveError("google did not return a refresh token")
        email = _email_for(client, data.get("access_token", ""))
    return TokenExchange(refresh_token=refresh_token, access_token=data.get("access_token", ""), email=email)


def refresh_access_token(settings: Settings, refresh_token: str) -> str:
    form = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            response = client.post(TOKEN_URL, data=form)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise DriveError(_CONNECTION_ERROR) from exc
    if response.status_code == 400:
        try:
            error = response.json().get("error")
        except ValueError:
            error = None
        if error == "invalid_grant":
            raise DriveNotConnected("drive_not_connected")
        raise DriveError(f"google token error {response.status_code}")
    if not (200 <= response.status_code < 300):
        raise DriveError(f"google token error {response.status_code}")
    return response.json()["access_token"]


def revoke(token: str) -> None:
    """Best effort: Google's revoke endpoint failing never blocks a disconnect. Only the status
    code or exception type is logged, never the token."""
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            response = client.post(REVOKE_URL, data={"token": token})
        if not (200 <= response.status_code < 300):
            log.info("drive token revoke returned status %s", response.status_code)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        log.info("drive token revoke failed: %s", type(exc).__name__)
