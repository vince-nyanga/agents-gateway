# Persistence

Agent Gateway stores conversations, executions, audit logs, schedules, and memories in a persistence backend. By default no persistence is configured — data lives only in memory for the lifetime of the process. To retain data across restarts, configure SQLite or PostgreSQL.

## What Gets Stored

| Data | Description |
|------|-------------|
| Conversations | Full message history per session |
| Executions | Run records including status, input, output, and timing |
| Audit logs | Immutable record of all agent invocations |
| Schedules | Persistent schedule state (pause/resume survives restarts) |
| Memories | Per-user and global agent memories (when memory is enabled) |

Executions are linked to conversations via `session_id`, so you can trace a full user session across multiple agent runs.

### Session Rehydration

When persistence is enabled, chat sessions survive server restarts. If an in-memory session expires or the server restarts, requesting a session by its ID automatically rehydrates it from the `conversations` table — no client-side changes needed. The rehydrated session respects the configured session TTL, so sessions that are older than the TTL are not restored.

**Known limitations:**

- Session **metadata** is not restored on rehydration (only messages are recovered).
- **Tool-call messages** (role `tool`) are excluded — only `user` and `assistant` messages are restored.
- If the last persisted message is a `user` message without a corresponding assistant reply, it is dropped to avoid sending an incomplete turn to the LLM.

## SQLite

SQLite is the easiest option for single-process deployments, local development, and small-scale production workloads.

**Install the extra:**

```bash
pip install agents-gateway[sqlite]
```

**Configure via `gateway.yaml`:**

```yaml
persistence:
  url: "sqlite+aiosqlite:///agent_gateway.db"
```

**Or configure fluently in code:**

```python
from agent_gateway import Gateway

gw = Gateway()
gw.use_sqlite("agent_gateway.db")
```

The path is relative to the working directory. Use an absolute path to pin the location regardless of where the process starts.

## PostgreSQL

PostgreSQL is recommended for production deployments, especially when running multiple Gateway processes behind a load balancer.

**Install the extra:**

```bash
pip install agents-gateway[postgres]
```

**Configure via `gateway.yaml`:**

```yaml
persistence:
  url: "postgresql+asyncpg://user:pass@host/db"
```

**Or configure fluently in code:**

```python
gw = Gateway()
gw.use_postgres("postgresql+asyncpg://user:pass@host/db")
```

### Connection Pool Tuning

The fluent method exposes pool settings:

```python
gw.use_postgres(
    url="postgresql+asyncpg://user:pass@host/db",
    pool_size=10,
    max_overflow=20,
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pool_size` | `10` | Number of persistent connections |
| `max_overflow` | `20` | Extra connections allowed above `pool_size` |

### Multi-Tenant Table Isolation

Two mechanisms allow multiple Gateway instances to share a single database without table name collisions.

**Table prefix** — prepends a string to every table name:

```yaml
persistence:
  url: "postgresql+asyncpg://user:pass@host/db"
  table_prefix: "tenant_a_"
```

```python
gw.use_postgres(url, table_prefix="tenant_a_")
```

**PostgreSQL schema** — places all tables in a named schema:

```yaml
persistence:
  url: "postgresql+asyncpg://user:pass@host/db"
  db_schema: "tenant_a"
```

```python
gw.use_postgres(url, schema="tenant_a")
```

The schema is created automatically on startup if it does not already exist.

Both options can be combined. Schema isolation is generally preferable in PostgreSQL because it keeps system catalogs clean and allows per-schema access control.

## Database Migrations

Agent Gateway uses [Alembic](https://alembic.sqlalchemy.org/) to manage schema migrations. Migrations run automatically when the Gateway starts:

```
INFO  Running database migrations (upgrade head)…
INFO  Done.
```

No manual step is needed for routine upgrades. If a migration fails the process exits rather than starting with a mismatched schema.

### CLI Commands

For manual control, use the `agents-gateway db` subcommands:

```bash
# Apply all pending migrations (same as startup auto-run)
agents-gateway db upgrade

# Upgrade to a specific revision
agents-gateway db upgrade abc123

# Roll back to a specific revision
agents-gateway db downgrade abc123

# Roll back one step
agents-gateway db downgrade -1

# Show the current revision applied to the database
agents-gateway db current

# List the full migration history
agents-gateway db history
```

!!! note
    Alembic requires a synchronous database driver. Agent Gateway automatically converts async driver URLs (e.g. `asyncpg`, `aiosqlite`) to their synchronous equivalents when running migrations. You do not need to maintain a separate migration URL.

## Custom Persistence Backend

If you need to store data in a system not covered by the built-in backends (DynamoDB, MongoDB, a proprietary data store), implement the `PersistenceBackend` protocol and register it with the Gateway.

```python
from agent_gateway.persistence import PersistenceBackend

class MyBackend(PersistenceBackend):
    async def save_conversation(self, conversation):
        ...

    async def get_conversation(self, session_id):
        ...

    # implement remaining protocol methods
    ...

gw = Gateway()
gw.use_persistence(MyBackend())
```

Refer to `agent_gateway.persistence.PersistenceBackend` for the full list of methods to implement.
