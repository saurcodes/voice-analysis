"""Log hygiene for the uvicorn access log. uvicorn logs every request's full path, query string
included; the Google OAuth callback's query carries the authorization `code` and `state`, which must
not reach the logs (nginx scrubs its own access line, but the proxied request is logged again here)."""
from __future__ import annotations

import logging

ACCESS_LOGGER = "uvicorn.access"
DRIVE_CALLBACK_PREFIX = "/api/drive/callback?"
REDACTED_CALLBACK = DRIVE_CALLBACK_PREFIX + "[redacted]"
ACCESS_ARGS_LEN = 5  # uvicorn: (client_addr, method, full_path, http_version, status_code)
PATH_INDEX = 2


class RedactDriveCallbackQuery(logging.Filter):
    """Rewrites the path argument of a uvicorn access record so `/api/drive/callback?...` logs as
    `/api/drive/callback?[redacted]`. Leaves any record that is not shaped like an access record alone."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == ACCESS_ARGS_LEN and isinstance(args[PATH_INDEX], str) \
                and args[PATH_INDEX].startswith(DRIVE_CALLBACK_PREFIX):
            record.args = args[:PATH_INDEX] + (REDACTED_CALLBACK,) + args[PATH_INDEX + 1:]
        return True


def install_access_log_filter() -> None:
    """Adds the redaction filter to the uvicorn access logger once; calling it again is a no-op."""
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, RedactDriveCallbackQuery) for f in logger.filters):
        logger.addFilter(RedactDriveCallbackQuery())
