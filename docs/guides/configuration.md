# Configuration

Agent Gateway is configured via a `gateway.yaml` file in the workspace directory. All settings have sensible defaults so you can start with an empty or minimal file and add sections as needed.

Configuration precedence (highest to lowest):

1. Environment variables (`AGENT_GATEWAY_*`)
2. `gateway.yaml`
3. Built-in defaults

## gateway.yaml reference

### server

Controls the HTTP server:

```yaml
server:
  host: "0.0.0.0"   # Bind address (default: 0.0.0.0)
  port: 8000         # Port (default: 8000)
  workers: 1         # Number of worker processes (default: 1)
```

### model

Default LLM settings used by all agents unless overridden in `AGENT.md`:

```yaml
model:
  default: "gpt-4o-mini"  # LiteLLM model identifier
  temperature: 0.1         # Sampling temperature (default: 0.1)
  max_tokens: 4096         # Maximum output tokens (default: 4096)
  fallback: null           # Fallback model if primary fails (default: none)
```

Model names follow [LiteLLM format](https://docs.litellm.ai/docs/providers). Examples: `gpt-4o`, `anthropic/claude-3-5-sonnet-20241022`, `gemini/gemini-2.0-flash`.

### guardrails

Hard limits applied to every agent execution:

```yaml
guardrails:
  max_tool_calls: 20          # Maximum tool calls per execution (default: 20)
  max_iterations: 10          # Maximum LLM reasoning iterations (default: 10)
  timeout_ms: 60000           # Execution timeout in milliseconds (default: 60000)
  max_delegation_depth: 3     # Maximum agent-to-agent delegation depth (default: 3)
```

An execution that hits any of these limits is stopped with the appropriate `stop_reason`.

### auth

Authentication configuration:

```yaml
auth:
  enabled: true
  mode: api_key            # api_key | oauth2 | composite | custom | none
  api_keys:
    - name: production
      key: "${API_KEY}"
      scopes: ["*"]
  oauth2:
    issuer: "https://auth.example.com"
    audience: "my-api"
    jwks_uri: null         # Auto-derived from issuer if null
    algorithms: [RS256, ES256]
    scope_claim: "scope"   # Use "scp" for Azure AD
    clock_skew_seconds: 30
  public_paths:
    - /v1/health
```

See [Authentication](authentication.md) for the full authentication guide.

### persistence

Database storage for execution records and audit logs:

```yaml
persistence:
  enabled: true
  backend: sqlite                                        # sqlite | postgres
  url: "sqlite+aiosqlite:///agent_gateway.db"           # Database URL
  table_prefix: ""                                       # Optional table name prefix
  db_schema: null                                        # PostgreSQL schema (default: public)
```

For PostgreSQL:

```yaml
persistence:
  backend: postgres
  url: "postgresql+asyncpg://user:password@host:5432/dbname"
  db_schema: "agent_gw"
```

### telemetry

OpenTelemetry tracing:

```yaml
telemetry:
  enabled: true
  service_name: "agent-gateway"
  exporter: console           # console | otlp | none
  endpoint: "http://localhost:4317"
  protocol: grpc              # grpc | http
  sample_rate: 1.0            # 0.0 to 1.0
```

### queue

Background execution queue for async agents:

```yaml
queue:
  backend: none                        # none | memory | redis | rabbitmq
  redis_url: "redis://localhost:6379/0"
  rabbitmq_url: "amqp://guest:guest@localhost:5672/"
  stream_key: "ag:executions"          # Redis stream key
  queue_name: "ag.executions"          # RabbitMQ queue name
  consumer_group: "ag-workers"         # Redis consumer group
  workers: 4                           # Number of concurrent workers
  max_retries: 3                       # Retry attempts for failed executions
  visibility_timeout_s: 300            # Seconds before a claimed job is requeued
  drain_timeout_s: 30                  # Seconds to wait for workers on shutdown
  default_execution_mode: sync         # sync | async (used when agent doesn't specify)
```

When `backend: none`, async executions run in-process using asyncio. For production, use `redis` or `rabbitmq`.

### scheduler

Controls cron-based agent scheduling (requires agents with `schedules:` defined):

```yaml
scheduler:
  enabled: true
  misfire_grace_seconds: 60  # How late a job can start before being skipped (default: 60)
  max_instances: 1           # Max concurrent instances of the same job (default: 1)
  coalesce: true             # Merge missed firings into one (default: true)
```

### context_retrieval

Controls how context is fetched from retrievers and static files:

```yaml
context_retrieval:
  retriever_timeout_seconds: 10.0   # Per-retriever timeout (default: 10.0)
  max_retrieved_chars: 50000        # Max total chars from all retrievers (default: 50000)
  max_context_file_chars: 100000    # Max chars from static context files (default: 100000)
```

### memory

Global memory defaults (overridable per-agent in `AGENT.md`):

```yaml
memory:
  enabled: false                   # Enable memory globally (default: false)
  max_injected_chars: 4000         # Max characters of memory injected per turn (default: 4000)
  extraction_model: null           # Model used for memory extraction (defaults to global model)
  auto_extract: false              # Auto-extract memories after each turn (default: false)
  max_memory_md_lines: 200         # Max lines in MEMORY.md file (default: 200)
  compaction:
    enabled: true                  # Enable automatic memory compaction (default: true)
    max_memories_per_scope: 100    # Trigger compaction when scope exceeds this (default: 100)
    compact_ratio: 0.5             # Fraction of memories to compact (default: 0.5)
    min_age_hours: 24              # Don't compact memories younger than this (default: 24)
    importance_threshold: 0.8      # Never compact memories with importance >= this (default: 0.8)
    decay_factor: 0.95             # Relevance decay per day since last access (default: 0.95)
```

### cors

Cross-Origin Resource Sharing headers:

```yaml
cors:
  enabled: false
  allow_origins:
    - "https://app.example.com"
  allow_methods: [GET, POST, DELETE, OPTIONS]
  allow_headers: [Authorization, Content-Type]
  allow_credentials: false
  max_age: 3600
```

`allow_credentials: true` cannot be combined with `allow_origins: ["*"]` — specify explicit origins instead.

### rate_limit

Rate limiting for API endpoints (requires `slowapi`):

```yaml
rate_limit:
  enabled: false
  default_limit: "100/minute"       # Default rate limit for all endpoints
  storage_uri: "redis://localhost:6379"  # Shared storage for multi-worker deployments
  trust_forwarded_for: false         # Use X-Forwarded-For header for client IP
```

Install the optional dependency: `pip install agents-gateway[rate-limiting]`

When running with multiple workers, set `storage_uri` to a Redis URL so rate limits are enforced across all processes. Without it, each worker maintains its own counter.

See the [Rate Limiting guide](rate-limiting.md) for details.

### dashboard

The built-in monitoring dashboard (opt-in):

```yaml
dashboard:
  enabled: false
  title: "Agent Gateway"
  logo_url: null
  favicon_url: null
  auth:
    enabled: true
    username: admin
    password: "${DASHBOARD_PASSWORD}"
    login_button_text: "Sign in with SSO"
    session_secret: ""          # Auto-generated if empty
    oauth2:                     # Optional OAuth2/OIDC SSO (replaces password auth)
      issuer: "https://auth.example.com"
      client_id: "dashboard-client"
      client_secret: "${DASHBOARD_CLIENT_SECRET}"
      scopes: [openid, profile, email]
  theme:
    mode: auto                  # light | dark | auto
    colors:
      primary: "#6366f1"
      primary_dark: "#818cf8"
      secondary: "#64748b"
      secondary_dark: "#94a3b8"
      surface: "#ffffff"
      surface_dark: "#141b2d"
      sidebar: "#0f172a"
      sidebar_dark: "#0b0f1a"
      danger: "#ef4444"
      danger_dark: "#f87171"
```

### notifications

Global notification backends:

```yaml
notifications:
  slack:
    enabled: false
    bot_token: "${SLACK_BOT_TOKEN}"
    default_channel: "#agent-alerts"
  webhooks:
    - name: monitoring
      url: "https://hooks.example.com/agent-events"
      secret: "${WEBHOOK_SECRET}"
      events: []               # Empty = all events
      payload_template: null   # Custom Jinja2 template for payload
```

Multiple webhook endpoints can be defined. Each has a unique `name` referenced in agent notification config.

### context

Arbitrary key-value data available to agent prompts and tool handlers:

```yaml
context:
  environment: production
  company_name: Acme Corp
  support_email: support@acme.com
```

### timezone

Global default timezone for schedules and timestamps:

```yaml
timezone: "UTC"   # IANA timezone string (default: UTC)
```

Valid values: `UTC`, `Europe/London`, `America/New_York`, `Asia/Tokyo`, etc.

## Environment variable overrides

Any configuration value can be overridden with an environment variable. The prefix is `AGENT_GATEWAY_` and nested keys are separated by `__` (double underscore):

```bash
AGENT_GATEWAY_SERVER__PORT=9000
AGENT_GATEWAY_MODEL__DEFAULT=gpt-4o
AGENT_GATEWAY_AUTH__ENABLED=false
AGENT_GATEWAY_PERSISTENCE__BACKEND=postgres
AGENT_GATEWAY_PERSISTENCE__URL=postgresql+asyncpg://...
```

Environment variables always take precedence over `gateway.yaml`.

## Variable interpolation

Use `${VAR_NAME}` syntax in any YAML string value to reference environment variables. The gateway substitutes the value at startup and raises an error if the variable is not set:

```yaml
auth:
  api_keys:
    - name: production
      key: "${PRODUCTION_API_KEY}"

persistence:
  url: "postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:5432/agent_gw"

notifications:
  slack:
    bot_token: "${SLACK_BOT_TOKEN}"
```

## Example configurations

### Development

```yaml
# gateway.yaml — development
server:
  port: 8000

model:
  default: "gpt-4o-mini"
  temperature: 0.1

auth:
  mode: api_key
  api_keys:
    - name: dev
      key: "dev-api-key-change-me"
      scopes: ["*"]

persistence:
  backend: sqlite
  url: "sqlite+aiosqlite:///agent_gateway.db"

telemetry:
  enabled: true
  exporter: console

cors:
  enabled: true

dashboard:
  enabled: true
  auth:
    username: admin
    password: "admin"

timezone: "UTC"
```

### Production

```yaml
# gateway.yaml — production
server:
  host: "0.0.0.0"
  port: 8000
  workers: 4

model:
  default: "gpt-4o"
  temperature: 0.1
  max_tokens: 8192
  fallback: "gpt-4o-mini"

guardrails:
  max_tool_calls: 30
  timeout_ms: 120000

auth:
  mode: oauth2
  oauth2:
    issuer: "${OAUTH2_ISSUER}"
    audience: "${OAUTH2_AUDIENCE}"
  public_paths:
    - /v1/health

persistence:
  backend: postgres
  url: "${DATABASE_URL}"
  db_schema: "agent_gw"

queue:
  backend: redis
  redis_url: "${REDIS_URL}"
  workers: 8
  max_retries: 3

telemetry:
  enabled: true
  service_name: "agent-gateway-prod"
  exporter: otlp
  endpoint: "${OTEL_EXPORTER_OTLP_ENDPOINT}"
  protocol: grpc
  sample_rate: 0.1

memory:
  enabled: true
  auto_extract: true
  compaction:
    enabled: true

cors:
  enabled: true
  allow_origins:
    - "https://app.example.com"
  allow_credentials: false

notifications:
  slack:
    enabled: true
    bot_token: "${SLACK_BOT_TOKEN}"
    default_channel: "#agent-alerts"
  webhooks:
    - name: pagerduty
      url: "${PAGERDUTY_WEBHOOK_URL}"
      secret: "${PAGERDUTY_WEBHOOK_SECRET}"

dashboard:
  enabled: true
  title: "Agent Gateway — Production"
  auth:
    enabled: true
    oauth2:
      issuer: "${OAUTH2_ISSUER}"
      client_id: "${DASHBOARD_CLIENT_ID}"
      client_secret: "${DASHBOARD_CLIENT_SECRET}"
  theme:
    mode: dark
    colors:
      primary: "#2563eb"
      sidebar: "#0f172a"

timezone: "UTC"
```
