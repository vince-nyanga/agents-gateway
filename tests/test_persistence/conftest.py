"""Shared fixtures for persistence tests."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agent_gateway.persistence.backends.sqlite import SqliteBackend


@pytest.fixture
async def sqlite_backend(tmp_path) -> SqliteBackend:
    """Create a temporary SQLite backend for testing."""
    db_path = tmp_path / "test.db"
    backend = SqliteBackend(path=str(db_path))
    await backend.initialize()
    yield backend
    await backend.dispose()


@pytest.fixture
async def db_engine(sqlite_backend: SqliteBackend) -> AsyncEngine:
    """Provide the engine from the SQLite backend."""
    return sqlite_backend._engine


@pytest.fixture
async def session_factory(sqlite_backend: SqliteBackend) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the test engine."""
    return sqlite_backend._session_factory
