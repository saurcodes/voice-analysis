"""Run Alembic programmatically (used by the backend at startup and by tests)."""
from __future__ import annotations

import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

# Freshly started containers (e.g. testcontainers Postgres) can report their
# internal readiness before the host-side port forward is actually accepting
# connections (observed with Rancher Desktop's user-mode networking). Retry
# the first connection briefly so callers don't have to special-case this.
_CONNECT_RETRIES = 5
_CONNECT_RETRY_DELAY_S = 0.5


def upgrade_to_head(url: str) -> None:
    """Upgrade the database at `url` to head. The explicit `url` wins over DATABASE_URL, .env and
    alembic.ini (env.py reads config.attributes first), and the app's logging config is left alone."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    cfg.attributes["sqlalchemy.url"] = url
    cfg.attributes["configure_logger"] = False
    for attempt in range(1, _CONNECT_RETRIES + 1):
        try:
            command.upgrade(cfg, "head")
            return
        except OperationalError:
            if attempt == _CONNECT_RETRIES:
                raise
            time.sleep(_CONNECT_RETRY_DELAY_S)
