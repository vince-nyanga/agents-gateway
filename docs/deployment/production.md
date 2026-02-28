# Production Deployment

This page covers the checklist for running Agent Gateway in production. Each item is a concrete action, not a suggestion.

---

## Checklist

### Use PostgreSQL

SQLite is the default and is suitable for development only. In production, run PostgreSQL and configure the connection before startup.

**Fluent API:**

```python
gw.use_postgres(
    url="postgresql+asyncpg://agw:password@db-host:5432/agw_db",
    pool_size=10,
    max_overflow=20,
)
```

**gateway.yaml:**

```yaml
persistence:
  backend: postgres
  url: ${DATABASE_URL}
```

**Run migrations before first start:**

```bash
agents-gateway db upgrade
```

Re-run `db upgrade` after every upgrade of the `agents-gateway` package to apply schema changes.

---

### Configure Authentication

Never run without authentication in production.

**API keys** (simplest):

```yaml
auth:
  enabled: true
  mode: api_key
  api_keys:
    - name: backend-service
      key: ${API_KEY_BACKEND}
      scopes: ["*"]
    - name: read-only-client
      key: ${API_KEY_READONLY}
      scopes: ["read"]
```

Keys must be long, random, and unique per caller. Store them in a secrets manager, not in source control.

**OAuth2/OIDC** (recommended for user-facing deployments):

```yaml
auth:
  enabled: true
  mode: oauth2
  oauth2:
    issuer: https://your-idp.example.com
    audience: your-api-audience
```

Or via the fluent API:

```python
gw.use_oauth2(
    issuer="https://your-idp.example.com",
    audience="your-api-audience",
)
```

---

### Configure CORS

Only enable CORS if a browser-based frontend will call the API directly. Always specify exact origins — never use `"*"` in production.

```python
gw.use_cors(
    allow_origins=["https://app.example.com"],
    allow_credentials=True,
)
```

```yaml
cors:
  enabled: true
  allow_origins:
    - https://app.example.com
  allow_credentials: true
```

---

### Enable the Dashboard with Strong Auth

The dashboard is disabled by default. If you enable it, protect it.

**Password auth:**

```python
gw.use_dashboard(
    auth_password=os.environ["DASHBOARD_PASSWORD"],
    title="My Agents",
)
```

**OAuth2/SSO (recommended):**

```python
gw.use_dashboard(
    oauth2_issuer="https://your-idp.example.com",
    oauth2_client_id=os.environ["DASHBOARD_CLIENT_ID"],
    oauth2_client_secret=os.environ["DASHBOARD_CLIENT_SECRET"],
)
```

Never deploy the dashboard without a password or SSO. An empty password is warned at startup but does not prevent startup.

---

### Set a Secret Key

Set `AGENT_GATEWAY_SECRET_KEY` for any functionality that requires encryption or signing (session cookies, webhook signatures, etc.).

```bash
export AGENT_GATEWAY_SECRET_KEY=$(openssl rand -hex 32)
```

---

### Use Redis or RabbitMQ for Async Agents

For agents that perform long-running work or need durable job queuing, configure a real queue backend. The in-memory queue loses jobs on restart and does not support multi-process deployments.

**Redis:**

```python
gw.use_redis_queue(url=os.environ["REDIS_URL"])
```

**RabbitMQ:**

```python
gw.use_rabbitmq_queue(url=os.environ["RABBITMQ_URL"])
```

---

### Configure OTLP Telemetry Export

Send traces and metrics to your observability platform.

```yaml
telemetry:
  enabled: true
  service_name: my-agent-service
  exporter: otlp
  endpoint: http://otel-collector:4317
  protocol: grpc
  sample_rate: 0.1   # sample 10% of traces in high-volume production
```

---

### Set Up Notifications

Configure notifications so errors and completion events reach your team.

```yaml
notifications:
  slack:
    enabled: true
    bot_token: ${SLACK_BOT_TOKEN}
    default_channel: "#agent-alerts"
```

Each agent controls which events trigger notifications via its `AGENT.md` frontmatter. Notifications that fail to deliver are logged as warnings and do not affect the execution result.

---

### Run with Multiple Workers or Behind Gunicorn

For production traffic, run multiple worker processes.

**Via gateway.yaml:**

```yaml
server:
  workers: 4
```

**Via gunicorn (recommended for production):**

```bash
gunicorn app:gw \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

Note: multiple processes require a shared queue backend (Redis or RabbitMQ) and a shared database. The in-memory queue does not work with multiple workers.

---

### Worker-Only Mode

To separate HTTP handling from background job processing, run dedicated worker processes that consume from the queue without listening for HTTP.

```bash
agents-gateway serve --worker-only
```

Worker-only processes connect to the same queue and database as the API server. Scale them independently to match job throughput.

---

### Health Check Endpoint

Use `GET /v1/health` for load balancer and container health checks. It requires no authentication and returns HTTP 200 with a JSON body.

```json
{
  "status": "ok",
  "agent_count": 3,
  "skill_count": 5,
  "tool_count": 8
}
```

`"status": "degraded"` indicates the gateway started but encountered workspace errors. The server is still operational.

---

## Summary Checklist

- [ ] PostgreSQL configured and `db upgrade` run
- [ ] API keys or OAuth2 configured — no unauthenticated access
- [ ] CORS configured with explicit origin(s) if needed
- [ ] Dashboard disabled, or protected with a strong password or SSO
- [ ] `AGENT_GATEWAY_SECRET_KEY` set
- [ ] Redis or RabbitMQ configured for async agents
- [ ] OTLP telemetry configured
- [ ] Notifications configured for error monitoring
- [ ] Running with multiple workers or behind gunicorn
- [ ] Health check at `GET /v1/health` wired to load balancer

---

## Sub-App Mounting

If you are integrating Agent Gateway into an existing FastAPI application rather than running it standalone, use `mount_to()`:

```python
from fastapi import FastAPI
from agent_gateway import Gateway

app = FastAPI()
gw = Gateway(workspace="./workspace")
gw.use_dashboard(auth_password=os.environ["DASHBOARD_PASSWORD"])
gw.mount_to(app, path="/ai")
```

All routes move under the mount prefix (`/ai/v1/health`, `/ai/dashboard/`, etc.). The health check endpoint becomes `{prefix}/v1/health`. All production recommendations above apply identically to mounted deployments.

See the [Sub-App Mounting guide](../guides/mounting.md) for the full walkthrough.
