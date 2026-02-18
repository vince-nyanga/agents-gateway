"""Shared fixtures for persistence tests."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agent_gateway.config import PersistenceConfig
from agent_gateway.persistence.session import create_db_engine, create_session_factory, init_db


@pytest.fixture
async def db_engine(tmp_path) -> AsyncEngine:
    """Create a temporary SQLite engine for testing."""
    db_path = tmp_path / "test.db"
    config = PersistenceConfig(
        enabled=True,
        backend="sqlite",
        url=f"sqlite+aiosqlite:///{db_path}",
    )
    engine = create_db_engine(config)
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the test engine."""
    return create_session_factory(db_engine)
