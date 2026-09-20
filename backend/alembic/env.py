"""Alembic environment.

The connection URL comes from the application settings rather than
alembic.ini, so `alembic upgrade head` always targets the same database the
service will use — and no credentials are ever written into a committed file.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Running `alembic` from backend/ puts backend/ on sys.path via
# prepend_sys_path, but running it from elsewhere (Render's build step, a
# script) does not. Make the import work either way.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config.settings import settings  # noqa: E402
from app.models import entities  # noqa: E402,F401  (registers every model on Base)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate compares the live database against this metadata.
target_metadata = entities.Base.metadata

# Set at runtime, never stored. `%` is escaped because ConfigParser performs
# interpolation on values it reads back — an unescaped percent sign in a
# URL-encoded password would raise InterpolationSyntaxError.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it, for review or manual apply."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # SQLite cannot ALTER most things in place. Batch mode rebuilds the
            # table around the change, which is what makes the same migration
            # script runnable on both the local and production databases.
            render_as_batch=_is_sqlite(),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
