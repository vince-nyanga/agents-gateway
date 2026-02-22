"""Example: custom pgvector-based memory backend.

Shows how consumers implement the MemoryBackend protocol with
vector search using pgvector and an embedding provider of their choice.

Requirements:
    pip install asyncpg pgvector sentence-transformers

Usage:
    from pgvector_memory import PgVectorMemoryBackend

    gw = Gateway(workspace="./workspace")
    gw.use_memory(PgVectorMemoryBackend(
        dsn="postgresql://user:pass@localhost/mydb",
    ))
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import asyncpg

from agent_gateway.memory.domain import (
    MemoryRecord,
    MemorySearchResult,
    MemorySource,
    MemoryType,
)

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
import numpy as np  # noqa: E402
from pgvector.asyncpg import register_vector  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

# Load embedding model once (384-dimensional by default)
_EMBED_MODEL = None


def _get_embed_model() -> SentenceTransformer:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _EMBED_MODEL


def _embed(text: str) -> np.ndarray:
    model = _get_embed_model()
    return model.encode(text, normalize_embeddings=True)


@dataclass
class PgVectorMemoryRepository:
    """Memory repository backed by PostgreSQL + pgvector.

    IMPORTANT: ``table`` must be a trusted, validated SQL identifier —
    never derived from user input.
    """

    pool: asyncpg.Pool
    table: str = "agent_memories"
    dimensions: int = 384

    def __post_init__(self) -> None:
        if not _SAFE_IDENT.match(self.table):
            raise ValueError(f"Unsafe table name: {self.table!r}")

    async def create_table(self) -> None:
        await self.pool.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await self.pool.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL DEFAULT 'semantic',
                source TEXT NOT NULL DEFAULT 'manual',
                importance REAL NOT NULL DEFAULT 0.5,
                access_count INTEGER NOT NULL DEFAULT 0,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                embedding vector({self.dimensions}),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await self.pool.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.table}_agent
            ON {self.table} (agent_id)
        """)
        await self.pool.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.table}_embedding
            ON {self.table}
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """)

    async def save(self, record: MemoryRecord) -> None:
        embedding = _embed(record.content)
        await self.pool.execute(
            f"""
            INSERT INTO {self.table}
                (id, agent_id, content, memory_type, source, importance,
                 access_count, metadata, embedding, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content,
                memory_type = EXCLUDED.memory_type,
                importance = EXCLUDED.importance,
                embedding = EXCLUDED.embedding,
                updated_at = EXCLUDED.updated_at
            """,
            record.id,
            record.agent_id,
            record.content,
            record.memory_type.value,
            record.source.value,
            record.importance,
            record.access_count,
            "{}",
            embedding,
            record.created_at,
            record.updated_at,
        )

    async def get(self, agent_id: str, memory_id: str) -> MemoryRecord | None:
        row = await self.pool.fetchrow(
            f"SELECT * FROM {self.table} WHERE id = $1 AND agent_id = $2",
            memory_id,
            agent_id,
        )
        return _row_to_record(row) if row else None

    async def list_memories(
        self,
        agent_id: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        if memory_type:
            rows = await self.pool.fetch(
                f"""SELECT * FROM {self.table}
                    WHERE agent_id = $1 AND memory_type = $2
                    ORDER BY updated_at DESC LIMIT $3 OFFSET $4""",
                agent_id,
                memory_type.value,
                limit,
                offset,
            )
        else:
            rows = await self.pool.fetch(
                f"""SELECT * FROM {self.table}
                    WHERE agent_id = $1
                    ORDER BY updated_at DESC LIMIT $2 OFFSET $3""",
                agent_id,
                limit,
                offset,
            )
        return [_row_to_record(r) for r in rows]

    async def search(
        self,
        agent_id: str,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        embedding = _embed(query)
        if memory_type:
            rows = await self.pool.fetch(
                f"""SELECT *, 1 - (embedding <=> $1) AS score
                    FROM {self.table}
                    WHERE agent_id = $2 AND memory_type = $3
                    ORDER BY embedding <=> $1 LIMIT $4""",
                embedding,
                agent_id,
                memory_type.value,
                limit,
            )
        else:
            rows = await self.pool.fetch(
                f"""SELECT *, 1 - (embedding <=> $1) AS score
                    FROM {self.table}
                    WHERE agent_id = $2
                    ORDER BY embedding <=> $1 LIMIT $3""",
                embedding,
                agent_id,
                limit,
            )
        return [
            MemorySearchResult(record=_row_to_record(r), score=float(r["score"]))
            for r in rows
        ]

    async def delete(self, agent_id: str, memory_id: str) -> bool:
        result = await self.pool.execute(
            f"DELETE FROM {self.table} WHERE id = $1 AND agent_id = $2",
            memory_id,
            agent_id,
        )
        return result == "DELETE 1"

    async def delete_all(self, agent_id: str) -> int:
        result = await self.pool.execute(
            f"DELETE FROM {self.table} WHERE agent_id = $1", agent_id
        )
        return int(result.split()[-1])

    async def count(self, agent_id: str) -> int:
        row = await self.pool.fetchrow(
            f"SELECT COUNT(*) as cnt FROM {self.table} WHERE agent_id = $1",
            agent_id,
        )
        return int(row["cnt"]) if row else 0


class PgVectorMemoryBackend:
    """Memory backend using PostgreSQL + pgvector for semantic search.

    This is a consumer-built implementation of the MemoryBackend protocol.
    The agent-gateway framework ships only the protocol and a file-based
    default — consumers bring their own vector store.
    """

    def __init__(
        self,
        dsn: str = "postgresql://localhost/agent_gateway",
        table: str = "agent_memories",
        pool_size: int = 5,
    ) -> None:
        self._dsn = dsn
        self._table = table
        self._pool_size = pool_size
        self._pool: asyncpg.Pool | None = None
        self._repo: PgVectorMemoryRepository | None = None

    async def initialize(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=self._pool_size
        )
        await register_vector(self._pool)
        self._repo = PgVectorMemoryRepository(pool=self._pool, table=self._table)
        await self._repo.create_table()

    async def dispose(self) -> None:
        if self._pool:
            await self._pool.close()

    @property
    def memory_repo(self) -> PgVectorMemoryRepository:
        assert self._repo is not None, "Backend not initialized"
        return self._repo


def _row_to_record(row: Any) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        agent_id=row["agent_id"],
        content=row["content"],
        memory_type=MemoryType(row["memory_type"]),
        source=MemorySource(row["source"]),
        importance=float(row["importance"]),
        access_count=int(row["access_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
