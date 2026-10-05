"""Drive error hierarchy. No token, client secret, or stack trace detail ever lands in these messages."""
from __future__ import annotations


class DriveError(RuntimeError):
    """Google returned an unexpected error; message carries only a status code."""


class DriveNotConnected(DriveError):
    """No usable connection for this user (never linked, or token revoked)."""


class DriveNotConfigured(DriveError):
    """Server lacks Google credentials."""


class DriveNotFound(DriveError):
    """File or folder not found / not readable."""
