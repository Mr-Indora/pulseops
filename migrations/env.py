"""Online-only Alembic env. Migrations are hand-written (no autogenerate), so no metadata import.

Always connects directly to Postgres (never via Toxiproxy) so fault injection cannot disturb it.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name:
    # disable_existing_loggers=False so running Alembic inside pytest/CLI keeps other loggers alive.
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("HOST_DATABASE_URL")
    if not url:
        raise RuntimeError("Set MIGRATION_DATABASE_URL (or HOST_DATABASE_URL) for Alembic")
    return url


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
