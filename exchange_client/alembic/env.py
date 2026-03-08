from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import sys
from pathlib import Path

# Make sure your project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import your Base so Alembic can see all your models
from db.models import Base
from db.session import engine  # reuse your existing engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is what tells autogenerate what the "target" schema looks like
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL only)."""
    #url = config.get_main_option("sqlalchemy.url")
    import os
    url = os.getenv("DATABASE_URL", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Tells autogenerate to also compare server defaults
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()