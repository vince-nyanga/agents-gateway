# Scheduling

Agent Gateway can run agents on a schedule using standard cron expressions. Schedules are defined in the agent's `AGENT.md` frontmatter and managed by an embedded [APScheduler](https://apscheduler.readthedocs.io/) instance.

## Defining a Schedule

Add a `schedules` list to the frontmatter of any `AGENT.md`:

```yaml
---
name: report-agent
schedules:
  - name: daily-report
    cron: "0 9 * * 1-5"
    message: "Generate the daily report"
    input: {}
    enabled: true
    timezone: "America/New_York"
---
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique name within this agent |
| `cron` | Yes | Standard 5-field cron expression |
| `message` | Yes | The message sent to the agent when the schedule fires |
| `input` | No | Additional structured input passed alongside the message |
| `enabled` | No | Defaults to `true`. Set to `false` to define but not activate |
| `timezone` | No | IANA timezone name. Defaults to UTC |

Cron expressions follow the standard 5-field format: `minute hour day-of-month month day-of-week`. For example:

| Expression | Meaning |
|------------|---------|
| `0 9 * * 1-5` | 9:00 AM every weekday |
| `*/15 * * * *` | Every 15 minutes |
| `0 0 1 * *` | Midnight on the first of every month |

### Schedule IDs

Every schedule has a stable ID in the format `{agent_id}:{schedule_name}`. For the example above that would be `report-agent:daily-report`. Use this ID with the management API and CLI.

## Gateway Configuration

Enable and tune the scheduler in `gateway.yaml`:

```yaml
scheduler:
  enabled: true
  misfire_grace_seconds: 60
  max_instances: 1
  coalesce: true
```

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Whether the scheduler runs at all |
| `misfire_grace_seconds` | `60` | How late a job can fire before it is considered missed |
| `max_instances` | `1` | Maximum concurrent instances of the same schedule |
| `coalesce` | `true` | Merge multiple missed firings into one |

## Overlap Prevention

By default `max_instances: 1` prevents a new run from starting while the previous one is still active — the new run is simply skipped. This is the right default for most agents that should not run concurrently.

If a run is still marked active after `2 × misfire_grace_seconds`, the Gateway assumes the previous run was orphaned (e.g. due to a process crash) and force-clears the lock before allowing the next run to proceed.

## Execution Dispatch

When a schedule fires:

- **Queue configured** — the run is enqueued to the queue backend and processed by a worker. This is the recommended path for longer-running agents.
- **No queue** — the run is invoked directly in the scheduler thread. Keep scheduled agents short if you are not using a queue.

## Managing Schedules at Runtime

The Gateway exposes a management API for schedules:

```python
# List all registered schedules and their current state
schedules = await gw.list_schedules()

# Pause a schedule (survives restarts if SQL persistence is configured)
await gw.pause_schedule("report-agent:daily-report")

# Resume a paused schedule
await gw.resume_schedule("report-agent:daily-report")

# Trigger a schedule immediately, outside its normal cadence
await gw.trigger_schedule("report-agent:daily-report")
```

!!! note
    Pause and resume state is only persisted across restarts when a SQL persistence backend is configured. Without persistence, all schedules return to their `AGENT.md` defaults on the next startup.

## CLI

List all registered schedules from the terminal:

```bash
agents-gateway schedules
```

Output shows each schedule's ID, cron expression, timezone, enabled state, and next fire time.

## Multi-Instance Deployment

When running multiple gateway instances behind a load balancer (e.g. with `server.workers > 1` or multiple containers), every instance runs its own embedded scheduler. Without coordination, the same schedule will fire on all instances simultaneously, causing duplicate agent executions.

Enable distributed locking to ensure only one instance fires each scheduled job:

```yaml
scheduler:
  enabled: true
  distributed_lock:
    enabled: true
    backend: auto   # auto | redis | postgres | none
```

### How it works

Before each scheduled job fires, the instance attempts to acquire an exclusive distributed lock for that schedule ID. The instance that wins the lock proceeds with execution; all others skip the firing. The lock expires automatically after `lock_ttl_seconds` (default 300 seconds), so a crashed instance can never hold the lock permanently.

### Backend selection

| Backend | Mechanism | When to use |
|---------|-----------|-------------|
| `auto` | Detects Redis queue → Redis lock; PostgreSQL persistence → PostgreSQL advisory lock | Recommended default |
| `redis` | Redis `SET NX EX` | Explicit Redis lock when queue backend is not Redis |
| `postgres` | `pg_try_advisory_lock` | Explicit PostgreSQL lock without a Redis queue |
| `none` | No-op (same as disabling) | Testing or intentional duplicate-execution tolerance |

With `backend: auto`, the gateway inspects the configured queue and persistence backends at startup:

- Queue backend is Redis → use Redis distributed lock (same connection)
- Persistence backend is PostgreSQL → use PostgreSQL advisory lock
- Neither → fall back to no-op (logs a warning when `enabled: true`)

### Redis backend

```yaml
scheduler:
  distributed_lock:
    enabled: true
    backend: redis
    redis_url: "${REDIS_URL}"   # Defaults to queue.redis_url when omitted
    key_prefix: "ag:sched-lock:"
    lock_ttl_seconds: 300
```

The Redis URL falls back to `queue.redis_url` when not explicitly set, so most Redis-queue deployments need no extra configuration.

### PostgreSQL backend

```yaml
scheduler:
  distributed_lock:
    enabled: true
    backend: postgres
    key_prefix: "ag:sched-lock:"
    lock_ttl_seconds: 300
```

The PostgreSQL backend uses `pg_try_advisory_lock` with a hash of the schedule ID as the lock key. It reuses the existing persistence connection pool — no separate connection string is needed.

### Configuration reference

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `false` | Enable distributed locking. Set to `true` for multi-instance deployments |
| `backend` | `"auto"` | Lock backend: `auto`, `redis`, `postgres`, or `none` |
| `redis_url` | *(from queue)* | Redis connection URL. Defaults to `queue.redis_url` when using the Redis backend |
| `key_prefix` | `"ag:sched-lock:"` | Prefix applied to all lock keys in Redis |
| `lock_ttl_seconds` | `300` | Lock expiry in seconds. Must exceed the maximum expected job duration |

!!! warning
    Set `lock_ttl_seconds` to a value comfortably greater than the longest expected agent execution time. If the lock expires before the job completes, another instance may fire the same schedule.

!!! note
    Distributed locking applies only to **scheduled** job firings. Manual triggers via `POST /v1/schedules/{id}/trigger` always execute regardless of the lock state.

## Per-User Schedules

In addition to global schedules defined in `AGENT.md`, users can create personal schedules from the dashboard. These schedules:

- Are scoped to a specific user and stored in the `user_schedules` table
- Can target any agent the user has access to (including configured personal agents)
- Are managed via the dashboard at `/dashboard/my-schedules`
- Support creating, toggling (pause/resume), and deleting schedules
- Use the same cron expression format as global schedules
- Appear on the main schedules page with a "Personal" badge alongside global schedules

Per-user schedules require SQL persistence to be enabled.
