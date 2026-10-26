from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base
from app import learning_support_models, models, video_models  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
# Keep an explicitly supplied Alembic URL intact.  Runtime deployments may
# still override it with ZHIXING_DATABASE_URL, while migration checks can use
# Config.set_main_option(...) to target an isolated fresh database.
if os.getenv("ZHIXING_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["ZHIXING_DATABASE_URL"])
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if connectable.dialect.name == "sqlite" and connectable.url.database not in {None, "", ":memory:"}:
        Path(connectable.url.database).parent.mkdir(parents=True, exist_ok=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
