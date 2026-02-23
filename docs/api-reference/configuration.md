# Configuration Reference

Agent Gateway is configured via `workspace/gateway.yaml`, with environment variables taking precedence over file values.

**Environment variable pattern:** prefix `AGENT_GATEWAY_`, nested sections separated by `__`.

```
AGENT_GATEWAY_SERVER__PORT=9000
AGENT_GATEWAY_MODEL__DEFAULT=gpt-4o
AGENT_GATEWAY_PERSISTENCE__BACKEND=postgres
```

**YAML `${VAR}` interpolation:** any value in `gateway.yaml` may reference environment variables using `${VAR_NAME}`. Gateway raises an error at startup if a referenced variable is undefined.

```yaml
persistence:
  url: ${DATABASE_URL}
```

Configuration is loaded once at startup. There is no live-reload of `gateway.yaml`.

---

## GatewayConfig

Root configuration object. Loaded from `workspace/gateway.yaml`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timezone` | `str` | `"UTC"` | IANA timezone name used by the scheduler (e.g. `"America/New_York"`). |
| `server` | `ServerConfig` | — | HTTP server settings. |
| `model` | `ModelConfig` | — | LLM model settings. |
| `guardrails` | `GuardrailsConfig` | — | Execution safety limits. |
| `auth` | `AuthConfig` | — | Authentication settings. |
| `notifications` | `NotificationsConfig` | — | Notification backend settings. |
| `persistence` | `PersistenceConfig` | — | Database persistence settings. |
| `telemetry` | `TelemetryConfig` | — | OpenTelemetry settings. |
| `queue` | `QueueConfig` | — | Async execution queue settings. |
| `scheduler` | `SchedulerConfig` | — | Cron scheduler settings. |
| `context_retrieval` | `ContextRetrievalConfig` | — | RAG context retrieval settings. |
| `memory` | `MemoryConfig` | — | Agent memory settings. |
| `cors` | `CorsConfig` | — | CORS middleware settings. |
| `dashboard` | `DashboardConfig` | — | Built-in web dashboard settings. |
| `context` | `dict[str, Any]` | `{}` | Arbitrary key-value context injected into all agent prompts. |

---

## ServerConfig

Controls the embedded uvicorn server when using `gw.run()` or `agents-gateway serve`.

Env prefix: `AGENT_GATEWAY_SERVER__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `str` | `"0.0.0.0"` | Bind address. |
| `port` | `int` | `8000` | Listen port. |
| `workers` | `int` | `1` | Number of uvicorn worker processes. |

---

## ModelConfig

Default LLM settings applied to all agents unless overridden in `AGENT.md` frontmatter.

Env prefix: `AGENT_GATEWAY_MODEL__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default` | `str` | `"gpt-4o-mini"` | Default model identifier (any LiteLLM model string). |
| `temperature` | `float` | `0.1` | Sampling temperature (0.0–2.0). |
| `max_tokens` | `int` | `4096` | Maximum output tokens per LLM call. |
| `fallback` | `str \| None` | `None` | Model to fall back to on primary model failure. |

---

## GuardrailsConfig

Safety limits applied per execution. Triggers `GuardrailTriggered` when exceeded.

Env prefix: `AGENT_GATEWAY_GUARDRAILS__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_tool_calls` | `int` | `20` | Maximum tool invocations per execution. Triggers reason `"max_tool_calls"`. |
| `max_iterations` | `int` | `10` | Maximum LLM reasoning steps per execution. Triggers reason `"max_iterations"`. |
| `timeout_ms` | `int` | `60000` | Maximum wall-clock time in milliseconds. Triggers reason `"timeout"`. |

---

## AuthConfig

Top-level authentication configuration. The fluent API (`use_api_keys`, `use_oauth2`) takes precedence over these settings.

Env prefix: `AGENT_GATEWAY_AUTH__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable authentication middleware. |
| `mode` | `str` | `"api_key"` | Auth strategy: `"api_key"`, `"oauth2"`, `"composite"`, `"custom"`, or `"none"`. |
| `api_keys` | `list[AuthKeyConfig]` | `[]` | API key records (used when `mode` is `"api_key"` or `"composite"`). |
| `oauth2` | `OAuth2Config \| None` | `None` | OAuth2 configuration (used when `mode` is `"oauth2"` or `"composite"`). |
| `public_paths` | `list[str]` | `["/v1/health"]` | Paths exempt from authentication. |

### AuthKeyConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | — | Human-readable name for the key (for logging/audit). |
| `key` | `str` | — | The plaintext API key. Hashed at load time; plaintext is not retained. |
| `scopes` | `list[str]` | `["*"]` | Scopes granted to this key. `"*"` grants all. |

### OAuth2Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `issuer` | `str` | — | Token issuer URL (e.g. `"https://auth.example.com"`). |
| `audience` | `str` | — | Expected `aud` claim value. |
| `jwks_uri` | `str \| None` | `None` | JWKS endpoint URL. Defaults to `{issuer}/.well-known/jwks.json`. |
| `algorithms` | `list[str]` | `["RS256", "ES256"]` | Allowed signing algorithms. |
| `scope_claim` | `str` | `"scope"` | JWT claim containing scopes. Use `"scp"` for Azure AD. |
| `clock_skew_seconds` | `int` | `30` | Allowed clock skew when validating `iat`/`exp`. |

---

## NotificationsConfig

Env prefix: `AGENT_GATEWAY_NOTIFICATIONS__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `slack` | `SlackConfig` | — | Slack notification settings. |
| `webhooks` | `list[WebhookEndpointConfig]` | `[]` | Webhook endpoint definitions. |
| `webhook_secret` | `str` | `""` | Default HMAC-SHA256 signing secret for all webhooks. |

### SlackConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable Slack notifications. |
| `bot_token` | `str` | `""` | Slack bot token (`xoxb-...`). |
| `default_channel` | `str` | `"#agent-alerts"` | Default channel for notifications. |

### WebhookEndpointConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | — | Endpoint name (referenced by agents in `AGENT.md`). |
| `url` | `str` | — | HTTPS URL to POST notifications to. |
| `secret` | `str` | `""` | Per-endpoint HMAC-SHA256 signing secret. Overrides the global `webhook_secret`. |
| `events` | `list[str]` | `[]` | Event types to forward. Empty list means all events. |
| `payload_template` | `str \| None` | `None` | Jinja2 template string for custom request body. |

---

## PersistenceConfig

Env prefix: `AGENT_GATEWAY_PERSISTENCE__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable persistence. When `False`, all repositories use null (in-memory) implementations. |
| `backend` | `str` | `"sqlite"` | Backend type: `"sqlite"` or `"postgres"`. |
| `url` | `str` | `"sqlite+aiosqlite:///agent_gateway.db"` | SQLAlchemy async DSN. |
| `table_prefix` | `str` | `""` | Optional prefix for all table names (e.g. `"ag_"`). |
| `db_schema` | `str \| None` | `None` | PostgreSQL schema name. Must pre-exist. Has no effect with SQLite. |

The fluent API (`use_sqlite`, `use_postgres`) overrides these settings.

---

## TelemetryConfig

Env prefix: `AGENT_GATEWAY_TELEMETRY__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable OpenTelemetry instrumentation. |
| `service_name` | `str` | `"agent-gateway"` | Service name reported in traces and metrics. |
| `exporter` | `str` | `"console"` | Exporter type: `"console"`, `"otlp"`, or `"none"`. |
| `endpoint` | `str` | `"http://localhost:4317"` | OTLP collector endpoint. |
| `protocol` | `str` | `"grpc"` | OTLP transport protocol: `"grpc"` or `"http"`. |
| `sample_rate` | `float` | `1.0` | Trace sampling rate (0.0–1.0). |

---

## QueueConfig

Env prefix: `AGENT_GATEWAY_QUEUE__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `backend` | `str` | `"none"` | Queue backend: `"none"`, `"memory"`, `"redis"`, or `"rabbitmq"`. |
| `redis_url` | `str` | `"redis://localhost:6379/0"` | Redis connection URL. |
| `rabbitmq_url` | `str` | `"amqp://guest:guest@localhost:5672/"` | RabbitMQ AMQP URL. |
| `stream_key` | `str` | `"ag:executions"` | Redis Streams key for execution jobs. |
| `queue_name` | `str` | `"ag.executions"` | RabbitMQ durable queue name. |
| `consumer_group` | `str` | `"ag-workers"` | Redis Streams consumer group name. |
| `workers` | `int` | `4` | Number of concurrent worker coroutines per process. |
| `max_retries` | `int` | `3` | Maximum retry attempts for failed jobs. |
| `visibility_timeout_s` | `int` | `300` | Seconds a job is invisible to other workers while being processed. |
| `drain_timeout_s` | `int` | `30` | Seconds to wait for in-flight jobs to complete on shutdown. |
| `default_execution_mode` | `str` | `"sync"` | Default execution mode for new requests: `"sync"` or `"async"`. |

---

## SchedulerConfig

Env prefix: `AGENT_GATEWAY_SCHEDULER__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable the cron scheduler. |
| `misfire_grace_seconds` | `int` | `60` | Seconds past the scheduled time within which a missed fire is still executed. |
| `max_instances` | `int` | `1` | Maximum concurrent instances of the same schedule. |
| `coalesce` | `bool` | `True` | Collapse multiple missed fires into a single execution. |

---

## ContextRetrievalConfig

Controls RAG retriever behaviour during prompt assembly.

Env prefix: `AGENT_GATEWAY_CONTEXT_RETRIEVAL__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `retriever_timeout_seconds` | `float` | `10.0` | Maximum time to wait for a retriever call before skipping it. |
| `max_retrieved_chars` | `int` | `50000` | Maximum characters injected from retriever results into the prompt. |
| `max_context_file_chars` | `int` | `100000` | Maximum characters read from workspace context files. |

---

## MemoryConfig

Global memory defaults. Individual agents override these in `AGENT.md` frontmatter.

Env prefix: `AGENT_GATEWAY_MEMORY__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable memory globally. Agents still need `memory.enabled: true` in their `AGENT.md`. |
| `max_injected_chars` | `int` | `4000` | Maximum characters of memory context injected into each prompt. |
| `extraction_model` | `str \| None` | `None` | Model for memory extraction. Defaults to the primary model. |
| `auto_extract` | `bool` | `False` | Automatically extract memories from each conversation turn. |
| `max_memory_md_lines` | `int` | `200` | Maximum lines in a `MEMORY.md` file (file backend only). |
| `compaction` | `CompactionConfig` | — | Memory compaction settings. |

### CompactionConfig

Prevents unbounded memory growth by summarising or discarding old memories.

Env prefix: `AGENT_GATEWAY_MEMORY__COMPACTION__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable compaction. |
| `max_memories_per_scope` | `int` | `100` | Trigger compaction when this many memories exist for a scope. |
| `compact_ratio` | `float` | `0.5` | Fraction of memories to remove during compaction (oldest first). |
| `min_age_hours` | `int` | `24` | Never compact memories younger than this. |
| `importance_threshold` | `float` | `0.8` | Never compact memories with importance score at or above this value. |
| `decay_factor` | `float` | `0.95` | Relevance score multiplier applied per day since last access. |

---

## CorsConfig

Env prefix: `AGENT_GATEWAY_CORS__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable CORS middleware. |
| `allow_origins` | `list[str]` | `["*"]` | Allowed origin(s). Use explicit origins when `allow_credentials` is `True`. |
| `allow_methods` | `list[str]` | `["GET", "POST", "DELETE", "OPTIONS"]` | Allowed HTTP methods. |
| `allow_headers` | `list[str]` | `["Authorization", "Content-Type"]` | Allowed request headers. |
| `allow_credentials` | `bool` | `False` | Allow cookies / `Authorization` headers in cross-origin requests. Wildcard origin is rejected when `True`. |
| `max_age` | `int` | `3600` | Preflight cache duration in seconds. |

---

## RateLimitConfig

Env prefix: `AGENT_GATEWAY_RATE_LIMIT__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable rate limiting middleware. Requires `slowapi`. |
| `default_limit` | `str` | `"100/minute"` | Default rate limit applied to all endpoints. Uses slowapi rate string format (e.g. `"10/second"`, `"100/minute"`, `"1000/hour"`). |
| `storage_uri` | `str \| None` | `None` | URI for shared rate limit storage (e.g. `"redis://localhost:6379"`). Required for consistent limits across multiple workers. |
| `trust_forwarded_for` | `bool` | `False` | Use the `X-Forwarded-For` header to identify clients. Enable when behind a reverse proxy. |

---

## SecurityConfig

Env prefix: `AGENT_GATEWAY_SECURITY__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable security headers middleware. Enabled by default (opt-out). |
| `x_content_type_options` | `str` | `"nosniff"` | Value for the `X-Content-Type-Options` header. |
| `x_frame_options` | `str` | `"DENY"` | Value for the `X-Frame-Options` header. Use `"SAMEORIGIN"` to allow same-origin framing. |
| `strict_transport_security` | `str` | `"max-age=31536000; includeSubDomains"` | Value for the `Strict-Transport-Security` header. Set to `""` to omit. |
| `content_security_policy` | `str` | `"default-src 'self'"` | Value for the `Content-Security-Policy` header on API paths. |
| `referrer_policy` | `str` | `"strict-origin-when-cross-origin"` | Value for the `Referrer-Policy` header. |
| `dashboard_content_security_policy` | `str` | *(relaxed CSP)* | CSP applied to `/dashboard` paths. Allows inline styles/scripts by default. |

---

## DashboardConfig

Env prefix: `AGENT_GATEWAY_DASHBOARD__`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Enable the dashboard at `/dashboard`. Opt-in. |
| `title` | `str` | `"Agent Gateway"` | Browser tab title and sidebar heading. |
| `logo_url` | `str \| None` | `None` | URL of a logo image displayed in the sidebar. |
| `auth` | `DashboardAuthConfig` | — | Dashboard authentication settings. |
| `theme` | `DashboardThemeConfig` | — | Visual theme settings. |

### DashboardAuthConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Require login to access the dashboard. |
| `username` | `str` | `"admin"` | Login username (password auth mode). |
| `password` | `str` | `""` | Login password. Empty string disables password protection (warned at startup). |
| `login_button_text` | `str` | `"Sign in with SSO"` | Text on the SSO login button (OAuth2 mode). |
| `session_secret` | `str` | `""` | Secret for signing session cookies. Auto-generated if empty. |
| `oauth2` | `DashboardOAuth2Config \| None` | `None` | OAuth2/OIDC configuration. Mutually exclusive with `password`. |

### DashboardOAuth2Config

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `issuer` | `str` | — | OIDC issuer URL. |
| `client_id` | `str` | — | OAuth2 client ID. |
| `client_secret` | `str` | — | OAuth2 client secret (confidential client; required). |
| `scopes` | `list[str]` | `["openid", "profile", "email"]` | OAuth2 scopes to request. |

### DashboardThemeConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `"light" \| "dark" \| "auto"` | `"auto"` | Color scheme. `"auto"` follows the user's OS preference. |
| `accent_color` | `str` | `"#6366f1"` | Legacy accent color. Maps to `colors.primary` if `colors.primary` is unchanged. |
| `accent_color_dark` | `str` | `"#818cf8"` | Legacy dark accent. Maps to `colors.primary_dark` if unchanged. |
| `colors` | `DashboardColorConfig` | — | Granular color overrides. |

### DashboardColorConfig

All values are CSS hex color strings.

| Field | Default (light) | Default (dark) | Description |
|-------|-----------------|----------------|-------------|
| `primary` | `"#6366f1"` | `"#818cf8"` | Buttons, links, active nav items. |
| `secondary` | `"#64748b"` | `"#94a3b8"` | Secondary actions, muted text. |
| `accent` | *(= primary)* | *(= primary_dark)* | Highlight color. Defaults to `primary` if empty. |
| `surface` | `"#ffffff"` | `"#141b2d"` | Card and panel backgrounds. |
| `sidebar` | `"#0f172a"` | `"#0b0f1a"` | Sidebar background. |
| `danger` | `"#ef4444"` | `"#f87171"` | Error states and destructive action buttons. |

---

## Full gateway.yaml Example

```yaml
timezone: Europe/London

server:
  port: 9000
  workers: 4

model:
  default: gpt-4o
  temperature: 0.2
  max_tokens: 8192

guardrails:
  max_tool_calls: 30
  timeout_ms: 120000

auth:
  enabled: true
  mode: api_key
  api_keys:
    - name: my-service
      key: ${API_KEY}
      scopes: ["*"]

persistence:
  backend: postgres
  url: ${DATABASE_URL}

telemetry:
  exporter: otlp
  endpoint: http://otel-collector:4317

queue:
  backend: redis
  redis_url: ${REDIS_URL}

notifications:
  slack:
    enabled: true
    bot_token: ${SLACK_BOT_TOKEN}
    default_channel: "#ops-alerts"

cors:
  enabled: true
  allow_origins:
    - https://app.example.com
  allow_credentials: true

dashboard:
  enabled: true
  title: My Agents
  auth:
    password: ${DASHBOARD_PASSWORD}
  theme:
    mode: dark
```
