"""Alembic environment: tells Alembic how to reach the database and which
tables the app expects (db_models.Base.metadata)."""

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

import db
from db_models import Base

load_dotenv(Path(__file__).parent.parent / ".env")

config = context.config
if config.config_file_name is not None:
    # Without disable_existing_loggers=False, loading this logging config
    # would silently switch off the app's own loggers in the same process.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # A caller (the migration test) may pass a URL; otherwise use DATABASE_URL.
    url = config.get_main_option("sqlalchemy.url") or db.database_url()
    if not url:
        raise RuntimeError("Set DATABASE_URL (in the environment or backend/.env) before running alembic.")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
