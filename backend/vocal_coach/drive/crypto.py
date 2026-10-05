"""Fernet encryption for Drive refresh tokens. Access tokens are never stored, so this is the only
secret this module ever touches."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from vocal_coach.drive.errors import DriveError


def encrypt_token(key: str, token: str) -> bytes:
    return Fernet(key.encode()).encrypt(token.encode())


def decrypt_token(key: str, blob: bytes) -> str:
    try:
        return Fernet(key.encode()).decrypt(blob).decode()
    except InvalidToken as exc:
        raise DriveError("stored token cannot be decrypted") from exc


def generate_key() -> str:
    """A fresh Fernet key, for the operator to put in DRIVE_TOKEN_KEY (see README)."""
    return Fernet.generate_key().decode()
