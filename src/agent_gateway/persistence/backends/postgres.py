"""PostgreSQL persistence backend.

Requires: pip install agent-gateway[postgres]
"""

from __future__ import annotations

from agent_gateway.persistence.backends.sql.base import SqlBackend, build_metadata, build_tables


class PostgresBackend(SqlBackend):
    """PostgreSQL persistence backend using asyncpg."""

    def __init__(
        self,
        url: str,
        schema: str | None = None,
        table_prefix: str = "",
        pool_size: int = 10,
        max_overflow: int = 20,
    ) -> None:
        try:
            import asyncpg  # noqa: F401
        except ImportError:
            raise ImportError(
                "PostgreSQL backend requires the postgres extra: "
                "pip install agent-gateway[postgres]"
            ) from None

        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.orm import registry

        # Normalize common PostgreSQL DSN formats
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        engine = create_async_engine(url, pool_size=pool_size, max_overflow=max_overflow)
        metadata = build_metadata(table_prefix=table_prefix, schema=schema)
        mapper_reg = registry(metadata=metadata)
        tables = build_tables(metadata, prefix=table_prefix)

        super().__init__(engine, metadata, mapper_reg, tables)
