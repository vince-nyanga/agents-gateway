# Dashboard

Agent Gateway ships with a built-in web dashboard for monitoring agents, browsing execution history, reviewing conversations, and chatting with agents directly from the browser. It is powered by HTMX for lightweight partial page updates without a separate frontend build step.

## Enabling the Dashboard

### Via `gateway.yaml`

```yaml
dashboard:
  enabled: true
```

### Via the fluent API

```python
from agent_gateway import Gateway

gw = Gateway()
gw.use_dashboard()
```

The dashboard is mounted at `/dashboard`. Once enabled, open that path in your browser while your service is running.

!!! tip "Mounted as a sub-app?"
    When the gateway is mounted via `gw.mount_to(app, path="/ai")`, the dashboard is available at `/ai/dashboard/`. All dashboard links, redirects, and static assets are prefix-aware automatically. See the [Sub-App Mounting guide](mounting.md) for details.

## Pages

| Page | Path | Description |
|---|---|---|
| Agents overview | `/dashboard/agents` | List of all registered agents with status and metadata. |
| Executions | `/dashboard/executions` | Filterable list of past executions. Filter by `agent_id`, `status`, or `session_id`. |
| Execution detail | `/dashboard/executions/{id}` | Full execution record including input, output, tool calls, and the distributed trace. |
| Conversations | `/dashboard/conversations` | List of conversation sessions across all agents. |
| Conversation detail | `/dashboard/conversations/{id}` | Full message history for a session. |
| Interactive chat | `/dashboard/chat` | Send messages to any agent and receive streaming responses over SSE. |
| Schedules | `/dashboard/schedules` | View global and personal cron-scheduled agent jobs. |
| My Schedules | `/dashboard/my-schedules` | Create and manage personal cron schedules. |
| Agent Setup | `/dashboard/agents/{id}/setup` | Configure personal agents (secrets, preferences). |
| Analytics | `/dashboard/analytics` | Cost and execution charts over time. Requires SQL persistence. |

## Authentication

Dashboard authentication is independent of your API authentication configuration. You can secure the dashboard with a username/password form or an OAuth2/OIDC provider regardless of how your API routes are protected.

### Password Authentication

Users log in with a username and password via an HTML form. A session cookie is issued on success and expires after 24 hours.

```python
gw.use_dashboard(
    auth_username="admin",
    auth_password="s3cr3t",
)
```

Or in `gateway.yaml`:

```yaml
dashboard:
  enabled: true
  auth:
    mode: password
    username: admin
    password: s3cr3t
```

### Admin Account

You can configure a separate admin account with elevated privileges. Admin users can toggle schedules and retry executions — regular users can only view them.

```python
gw.use_dashboard(
    auth_username="user",
    auth_password="userpass",
    admin_username="admin",
    admin_password="supersecret",
)
```

Or in `gateway.yaml`:

```yaml
dashboard:
  enabled: true
  auth:
    username: user
    password: userpass
    admin_username: admin
    admin_password: supersecret
```

The admin account is completely separate from regular user credentials. Both are valid for login but result in different session roles. Admin status is re-derived on every request from the config, so changing the `admin_username` takes effect immediately after restart.

OAuth2 users are always regular (non-admin) users — admin access requires password login.

### OAuth2 / OIDC

Use the Authorization Code flow with any OIDC-compliant provider (Google, Entra ID, Okta, Keycloak, etc.).

```python
gw.use_dashboard(
    auth_mode="oidc",
    auth_issuer="https://accounts.google.com",
    auth_client_id="your-client-id",
    auth_client_secret="your-client-secret",
)
```

Or in `gateway.yaml`:

```yaml
dashboard:
  enabled: true
  auth:
    mode: oidc
    issuer: "https://accounts.google.com"
    client_id: "your-client-id"
    client_secret: "your-client-secret"
```

#### Admin Fallback Login with OAuth2

When OAuth2 is configured as the primary login method, you can also configure admin credentials to provide break-glass access. This is useful when the OAuth2 provider is unavailable or when you need direct admin access without going through SSO.

```python
gw.use_dashboard(
    oauth2_issuer="https://accounts.google.com",
    oauth2_client_id="your-client-id",
    oauth2_client_secret="your-client-secret",
    admin_username="admin",
    admin_password="supersecret",
)
```

When both OAuth2 and admin credentials are configured, the login page shows the SSO button as the primary option with a collapsible "Sign in with admin credentials" section below it. The admin form auto-expands if a login error occurs.

## Branding

You can customise the dashboard's visual identity beyond just colours. Three dedicated fields control the service name, icon, and favicon displayed throughout the dashboard.

### Title

The `title` field sets the browser tab title and the heading displayed in the sidebar navigation.

```yaml
dashboard:
  enabled: true
  title: My Agent Service
```

### Subtitle

The `subtitle` field replaces the default `"AI Control Plane"` tagline shown beneath the service name in the sidebar and on the login page branding widget.

```yaml
dashboard:
  enabled: true
  subtitle: "Powered by ACME Corp"
```

### Logo

The `logo_url` field sets a branding image for both the sidebar header and the login page. Any image format the browser can render works — SVG, PNG, and WebP are all fine.

```yaml
dashboard:
  enabled: true
  logo_url: /static/logo.png
```

When `logo_url` is not set, the dashboard falls back to the built-in Material `hub` icon.

### Favicon

Set `favicon_url` to replace the default browser tab icon.

```yaml
dashboard:
  enabled: true
  favicon_url: /static/favicon.ico
```

### User Avatar

The topbar avatar uses initials generated by [ui-avatars.com](https://ui-avatars.com). When a user has a `display_name` set (e.g. via OAuth2 claims), the avatar uses the full name for initials (e.g. "JD" for "Jane Doe"). If no `display_name` is available, it falls back to the `username`.

### Full branding example

```python
gw.use_dashboard(
    title="ACME Agent Platform",
    subtitle="Powered by ACME Corp",
    logo_url="/static/wordmark.png",
    favicon_url="/static/favicon.ico",
    auth_password="s3cr3t",
)
```

Or in `gateway.yaml`:

```yaml
dashboard:
  enabled: true
  title: ACME Agent Platform
  subtitle: "Powered by ACME Corp"
  logo_url: /static/wordmark.png
  favicon_url: /static/favicon.ico
```

## Fluent API Reference

`gw.use_dashboard()` accepts keyword arguments to configure the dashboard inline without a config file:

```python
gw.use_dashboard(
    title="My Agent Service",          # Browser tab title and header text
    subtitle="AI Control Plane",       # Tagline beneath the title
    logo_url="/static/logo.png",       # Branding image for sidebar and login page
    favicon_url="/static/favicon.ico", # Browser tab favicon
    auth_username="admin",             # Password auth username
    auth_password="s3cr3t",            # Password auth password
    admin_username="admin",            # Separate admin account username
    admin_password="supersecret",      # Separate admin account password
    auth_mode="oidc",                  # "password" | "oidc" | None
    auth_issuer="https://...",         # OIDC issuer URL
    auth_client_id="...",              # OIDC client ID
    auth_client_secret="...",          # OIDC client secret
    theme="dark",                      # "light" | "dark" | "auto"
    primary_color="#6366f1",           # Primary accent color (hex)
)
```

Fluent API values take precedence over anything set in `gateway.yaml`.

## Theming

The dashboard supports light, dark, and system-preference-aware (`auto`) modes, plus a full set of color overrides. Colors can be specified for both light and dark variants.

```yaml
dashboard:
  enabled: true
  theme:
    mode: auto          # light | dark | auto
    colors:
      primary: "#6366f1"
      primary_dark: "#818cf8"
      secondary: "#64748b"
      secondary_dark: "#94a3b8"
      accent: "#f59e0b"
      accent_dark: "#fbbf24"
      surface: "#ffffff"
      surface_dark: "#1e1e2e"
      sidebar: "#f1f5f9"
      sidebar_dark: "#181825"
      danger: "#ef4444"
      danger_dark: "#f87171"
```

Each `*_dark` variant is applied when the UI is in dark mode.

## Personal Agents in the Dashboard

Agents with `scope: personal` are visually distinguished in the dashboard:

- **Agent cards** show a purple "personal" badge, plus a green "configured" or amber "setup required" badge based on the current user's configuration status.
- **Unconfigured personal agents** display a "Setup" button instead of "Chat", linking to the setup page.
- **Setup page** (`/dashboard/agents/{id}/setup`) renders a dynamic form from the agent's `setup_schema`, with support for text inputs, password fields (for sensitive values), dropdowns (for enums), array inputs, and custom instructions.
- **Chat page** blocks messaging to unconfigured personal agents and shows a setup banner.
- **Schedules** page shows both global (agent-defined) and personal (user-created) schedules with visual badges. Users can create, toggle, and delete personal schedules from `/dashboard/my-schedules`.

Personal agents require `AGENT_GATEWAY_SECRET_KEY` to be set for encrypting user secrets.

## Admin Management

Admin users have access to additional management features in the dashboard. These require logging in with the `admin_username` / `admin_password` credentials.

### Agent Detail & Edit

Click an agent's name on the Agents page to open the detail page (`/dashboard/agents/{id}/detail`). The detail page shows:

- Current configuration (description, model, tags, execution mode)
- An edit form for mutable frontmatter fields
- Read-only info (skills, schedules, delegates, scope, memory)
- An enable/disable toggle

**Editable fields:** `description`, `display_name`, `tags`, `model.name`, `model.temperature`, `model.max_tokens`, `execution_mode`.

**Not editable from the dashboard:** `skills`, `schedules`, `delegates_to`, `scope`, `input_schema`, `setup_schema`, `notifications`, `context`, `retrievers`, `memory`, and the markdown prompt body.

Edits are written to `AGENT.md` frontmatter on disk and trigger a workspace reload. Changes take effect immediately and survive restarts.

### Agent Enable/Disable

Each agent has an `enabled` frontmatter field (defaults to `true` when absent). Toggling this from the dashboard:

1. Writes `enabled: false` (or `true`) to `AGENT.md` frontmatter
2. Triggers a workspace reload
3. Disabled agents return **422** from the invoke and chat API endpoints
4. Disabled agents show a "Disabled" badge and are grayed out on the dashboard

This is a persistent change — it survives gateway restarts because it is written to disk.

### Schedule Editing

Admin users can click the edit icon on the Schedules page to open the schedule detail page (`/dashboard/schedules/{id}/detail`). The edit form allows changing:

- **Cron expression** (5-part cron syntax)
- **Message** (the text sent to the agent)
- **Timezone**
- **Enabled** toggle

Schedule edits update both APScheduler (runtime) and the persistence record. However, **schedule edits do NOT update AGENT.md**. On gateway restart, `AGENT.md` values take precedence and any runtime edits are lost.

## Analytics

The analytics page renders cost and execution volume charts over configurable time windows. It requires a SQL persistence backend to be configured — the in-memory default does not support the aggregation queries needed for analytics.

See the [Persistence guide](persistence.md) for details on configuring a SQL backend.
