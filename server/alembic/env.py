"""Alembic env for dagger_server.

Reads the DB URL from env `DAGGER_DB_URL` (falling back to the alembic.ini
`sqlalchemy.url`). Targets `dagger_server.models.Base.metadata` so autogenerate
sees all core tables.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure server/src is importable when alembic runs standalone.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dagger_server.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Env override takes precedence over alembic.ini's sqlalchemy.url.
env_url = os.environ.get("DAGGER_DB_URL")
if env_url:
    config.set_main_option("sqlalchemy.url", env_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
