"""SQLite persistence backend.

Requires: pip install agent-gateway[sqlite]
"""

from __future__ import annotations

from agent_gateway.persistence.backends.sql.base import SqlBackend, build_metadata, build_tables


class SqliteBackend(SqlBackend):
    """SQLite persistence backend using aiosqlite."""

    def __init__(
        self,
        path: str = "agent_gateway.db",
        table_prefix: str = "",
    ) -> None:
        try:
            import aiosqlite  # noqa: F401
        except ImportError:
            raise ImportError(
                "SQLite backend requires the sqlite extra: pip install agent-gateway[sqlite]"
            ) from None

        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.orm import registry

        url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url, connect_args={"check_same_thread": False})
        metadata = build_metadata(table_prefix=table_prefix)
        mapper_reg = registry(metadata=metadata)
        tables = build_tables(metadata, prefix=table_prefix)

        super().__init__(engine, metadata, mapper_reg, tables)
