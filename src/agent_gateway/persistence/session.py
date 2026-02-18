"""Database engine and session management for async SQLAlchemy."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agent_gateway.config import PersistenceConfig
from agent_gateway.persistence.models import Base

logger = logging.getLogger(__name__)


def create_db_engine(config: PersistenceConfig) -> AsyncEngine:
    """Create an async SQLAlchemy engine from configuration.

    Args:
        config: Persistence configuration with backend type and connection URL.
    """
    connect_args = {}
    if config.backend == "sqlite":
        # SQLite needs check_same_thread=False for async usage
        connect_args["check_same_thread"] = False

    return create_async_engine(
        config.url,
        echo=False,
        connect_args=connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory.

    Always uses expire_on_commit=False to avoid lazy-load issues in async context.
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def init_db(engine: AsyncEngine) -> None:
    """Create all database tables if they don't exist.

    Uses Base.metadata.create_all for simple auto-creation.
    For production migrations, use Alembic (planned for v1.1+).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")
