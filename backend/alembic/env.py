import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, create_engine
from sqlalchemy import pool
from alembic import context

# Add backend directory to path so models can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_settings
from core.database import Base
from models.models import (
    User, Organization, Document, Chunk, Review, Chat, QueryLog, CacheEntry,
)

# ── DATABASE CONNECTION LOGIC ──
# 1. First, check for an explicit '-x db_url=...' passed via command line
# 2. Otherwise, use the URL from the central settings (env files)
settings = get_settings()
cmd_line_url = context.get_x_argument(as_dictionary=True).get("db_url")
DATABASE_URL = cmd_line_url or settings.DATABASE_URL_SYNC

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    # Use create_engine directly with our resolved DATABASE_URL
    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

