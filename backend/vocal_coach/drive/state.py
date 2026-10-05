"""Signed, time-limited OAuth `state` tokens binding a Drive consent flow to one user and one
browser (the nonce is also set as an HttpOnly cookie by `/drive/connect`), plus the in-memory
ledger that makes each state single-use."""
from __future__ import annotations

import secrets
import threading
import time
import uuid
from collections.abc import Callable

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from vocal_coach.drive.errors import DriveStateError

STATE_MAX_AGE_S = 600
_SALT = "drive-oauth"
INVALID_STATE_MESSAGE = "invalid or expired state"


def new_nonce() -> str:
    return secrets.token_urlsafe(16)


def sign_state(secret_key: str, user_id: uuid.UUID, nonce: str) -> str:
    serializer = URLSafeTimedSerializer(secret_key, salt=_SALT)
    return serializer.dumps({"user_id": str(user_id), "nonce": nonce})


def verify_state(secret_key: str, state: str) -> tuple[uuid.UUID, str]:
    """Returns `(user_id, nonce)`; raises `DriveStateError` for a tampered, expired or malformed state."""
    serializer = URLSafeTimedSerializer(secret_key, salt=_SALT)
    try:
        payload = serializer.loads(state, max_age=STATE_MAX_AGE_S)
    except (BadSignature, SignatureExpired) as exc:
        raise DriveStateError(INVALID_STATE_MESSAGE) from exc
    try:
        user_id = uuid.UUID(payload["user_id"])
        nonce = payload["nonce"]
    except (KeyError, TypeError, ValueError) as exc:
        raise DriveStateError(INVALID_STATE_MESSAGE) from exc
    if not isinstance(nonce, str) or not nonce:
        raise DriveStateError(INVALID_STATE_MESSAGE)
    return user_id, nonce


class ConsumedNonces:
    """Nonces of states already used at the callback, remembered for as long as a state can be
    valid. Per process: a multi-replica deployment would need a shared store (not needed here)."""

    def __init__(self, ttl_s: float = STATE_MAX_AGE_S, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def consume(self, nonce: str) -> bool:
        """True the first time a nonce is seen (within the TTL), False on any later use."""
        now = self._clock()
        with self._lock:
            self._seen = {n: expiry for n, expiry in self._seen.items() if expiry > now}
            if nonce in self._seen:
                return False
            self._seen[nonce] = now + self._ttl_s
            return True
