"""
Alembic env.py — async SQLAlchemy + Supabase/PostgreSQL.

Reads DATABASE_URL from .env via app.config.get_settings().
Supports both offline (SQL dump) and online (asyncpg) modes.
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Add backend/ to sys.path so app.* imports work ───────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.models.base import Base
# Import all models so Base.metadata is fully populated
import app.models.tables  # noqa: F401

# ── Alembic Config ────────────────────────────────────────────────────────────
config = context.config

# Set SQLAlchemy URL from our Settings (overrides alembic.ini placeholder)
settings = get_settings()
if settings.db_configured:
    # Alembic needs a synchronous URL for offline mode; async for online.
    # We store asyncpg URL; replace for sync when needed.
    config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ── Offline mode ──────────────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online async mode ─────────────────────────────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
