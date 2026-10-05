"""Signed, time-limited OAuth `state` tokens binding a Drive consent flow to one user."""
from __future__ import annotations

import secrets
import uuid

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from vocal_coach.drive.errors import DriveError

STATE_MAX_AGE_S = 600
_SALT = "drive-oauth"
_INVALID_STATE_MESSAGE = "invalid or expired state"


def sign_state(secret_key: str, user_id: uuid.UUID) -> str:
    serializer = URLSafeTimedSerializer(secret_key, salt=_SALT)
    return serializer.dumps({"user_id": str(user_id), "nonce": secrets.token_urlsafe(16)})


def verify_state(secret_key: str, state: str) -> uuid.UUID:
    serializer = URLSafeTimedSerializer(secret_key, salt=_SALT)
    try:
        payload = serializer.loads(state, max_age=STATE_MAX_AGE_S)
    except (BadSignature, SignatureExpired) as exc:
        raise DriveError(_INVALID_STATE_MESSAGE) from exc
    try:
        return uuid.UUID(payload["user_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DriveError(_INVALID_STATE_MESSAGE) from exc
