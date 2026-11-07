"""Alembic migration environment for ClaimSage."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from claimsage.db import models  # noqa: F401
from claimsage.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url_value = os.environ.get("DATABASE_URL")
if not database_url_value:
    raise RuntimeError("DATABASE_URL must be explicitly set for Alembic.")

try:
    database_url = make_url(database_url_value)
except (ArgumentError, TypeError, ValueError):
    raise RuntimeError("DATABASE_URL must be a valid PostgreSQL URL.") from None

if database_url.get_backend_name() != "postgresql":
    raise RuntimeError("Alembic requires a PostgreSQL DATABASE_URL.")
ALLOWED_DATABASES = {"claimsage_test", "claimsage"}
if database_url.database not in ALLOWED_DATABASES:
    raise RuntimeError(
        f"Alembic is restricted to approved databases: {ALLOWED_DATABASES}."
    )

# Escaping percent signs prevents ConfigParser interpolation errors.
config.set_main_option(
    "sqlalchemy.url",
    database_url_value.replace("%", "%%"),
)

# Register all SQLAlchemy models for automatic migration generation.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        database_name = connection.execute(
            text("SELECT current_database()")
        ).scalar_one()
        if database_name not in ALLOWED_DATABASES:
            raise RuntimeError(
                f"Alembic is restricted to approved databases: {ALLOWED_DATABASES}."
            )

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

