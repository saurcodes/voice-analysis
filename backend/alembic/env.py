from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from vocal_coach.settings import get_settings
from vocal_coach.storage.models import Base

config = context.config
# The CLI configures logging from alembic.ini. Programmatic callers (upgrade_to_head) set
# configure_logger=False so the app's logging setup is left alone. Never disable existing loggers.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    """Precedence: -x url=... > config.attributes["sqlalchemy.url"] (programmatic) > DATABASE_URL env
    > Settings (also honours .env) > alembic.ini."""
    x_args = context.get_x_argument(as_dictionary=True)
    return (x_args.get("url")
            or config.attributes.get("sqlalchemy.url")
            or os.environ.get("DATABASE_URL")
            or get_settings().database_url
            or config.get_main_option("sqlalchemy.url"))


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # The URL goes straight to create_engine (not through set_main_option), so a '%' in a
    # password is never interpreted by configparser.
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
