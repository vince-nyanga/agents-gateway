# MCP Servers

Agent Gateway can connect to external [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers and expose their tools to your agents. This lets you integrate any MCP-compatible tool server without writing Python code.

## Quick Start

### 1. Register a server

**Fluent API (in code):**

```python
gw.add_mcp_server(
    name="my-tools",
    transport="stdio",
    command="python",
    args=["-m", "my_mcp_server"],
)
```

**Admin API (at runtime):**

```bash
curl -X POST http://localhost:8000/v1/admin/mcp-servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-tools",
    "transport": "stdio",
    "command": "python",
    "args": ["-m", "my_mcp_server"]
  }'
```

### 2. Assign to agents

In your agent's `AGENT.md` frontmatter:

```yaml
---
description: "My agent"
mcp_servers:
  - my-tools
---
```

If no agent references `mcp_servers`, all agents can use the MCP tools. If at least one agent lists `mcp_servers`, only those agents get access to the listed servers' tools.

### 3. Tools are auto-discovered

On startup, agent-gateway connects to each MCP server, discovers its tools, and registers them with namespaced names: `{server_name}__{tool_name}`.

## Transports

### stdio

The gateway spawns the MCP server as a subprocess:

```python
gw.add_mcp_server(
    name="my-tools",
    transport="stdio",
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    env={"NODE_ENV": "production"},  # optional env vars
)
```

### streamable_http

Connect to a remote MCP server over HTTP:

```python
gw.add_mcp_server(
    name="remote-tools",
    transport="streamable_http",
    url="https://mcp.example.com/mcp",
    headers={
        "Authorization": "Bearer sk-...",
        "X-API-Version": "2024-01-01",
    },
)
```

The `headers` parameter accepts a `dict[str, str]` of HTTP headers to send with every request. All header values are **encrypted at rest** -- any header can contain sensitive data like API keys or tokens.

For legacy compatibility, credential-based header patterns are still supported:

- `{"bearer_token": "..."}` -- sets `Authorization: Bearer ...`
- `{"api_key": "...", "api_key_header": "X-Api-Key"}` -- sets the named header

## OAuth2 Authentication

For MCP servers that require OAuth2 authentication, Agent Gateway supports automatic token refresh via built-in providers or custom token providers.

### OAuth2 Client Credentials

Use `auth_type: "oauth2_client_credentials"` in the credentials dict to automatically fetch and refresh tokens using the OAuth2 client credentials grant:

```python
gw.add_mcp_server(
    name="secure-tools",
    transport="streamable_http",
    url="https://mcp.example.com/mcp",
    credentials={
        "auth_type": "oauth2_client_credentials",
        "token_url": "https://auth.example.com/oauth2/token",
        "client_id": "my-client-id",
        "client_secret": "my-client-secret",
        "scopes": ["read", "write"],          # optional
        "extra_params": {"audience": "my-api"},  # optional
    },
)
```

### Google Service Account

Use `auth_type: "google_service_account"` with a service account JSON key. Requires the `gcp` extra (`pip install agent-gateway[gcp]`):

```python
gw.add_mcp_server(
    name="gcp-tools",
    transport="streamable_http",
    url="https://mcp.example.com/mcp",
    credentials={
        "auth_type": "google_service_account",
        "service_account_json": { ... },  # service account key dict
        "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
    },
)
```

### Custom Token Provider

For advanced use cases, implement the `McpTokenProvider` protocol and pass it directly:

```python
from agent_gateway.mcp import McpTokenProvider

class MyTokenProvider:
    server_name: str = "my-server"

    async def get_token(self) -> str:
        # Your custom token acquisition logic
        return "my-access-token"

gw.add_mcp_server(
    name="my-server",
    transport="streamable_http",
    url="https://mcp.example.com/mcp",
    token_provider=MyTokenProvider(),
)
```

The `McpTokenProvider` protocol, `McpHttpAuth`, and `OAuth2ClientCredentialsProvider` are all exported from `agent_gateway.mcp`.

## Configuration

Global MCP settings in `gateway.yaml` or `GatewayConfig`:

```yaml
mcp:
  tool_call_timeout_ms: 30000    # per-tool-call timeout (default: 30s)
  connection_timeout_ms: 10000   # connection startup timeout (default: 10s)
```

## Credential Security

When using the Admin API or Dashboard, `headers`, `credentials`, and `env` values are encrypted at rest using Fernet symmetric encryption. The encryption key is derived from `AGENT_GATEWAY_SECRET_KEY` (or auto-generated). Header and credential values are never exposed in API responses -- only key names are returned.

## Dashboard

The MCP Servers page (admin only) lets you:

- View all configured servers with connection status
- Add new servers (stdio or streamable_http)
- **Headers UI** -- add key-value HTTP headers via a dynamic form (streamable_http only). Headers are encrypted at rest.
- **Advanced Auth** -- configure OAuth2 or Google Service Account credentials via a collapsible section
- **Test connection** -- verify connectivity without affecting the live connection
- Refresh (reconnect and rediscover tools)
- Delete servers
- Browse discovered tools per server

## Admin API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/admin/mcp-servers` | Create server config |
| `GET` | `/v1/admin/mcp-servers` | List all servers |
| `GET` | `/v1/admin/mcp-servers/{id}` | Get server details |
| `PUT` | `/v1/admin/mcp-servers/{id}` | Update server config |
| `DELETE` | `/v1/admin/mcp-servers/{id}` | Delete server |
| `POST` | `/v1/admin/mcp-servers/{id}/test` | Test connection (ephemeral) |
| `POST` | `/v1/admin/mcp-servers/{id}/refresh` | Reconnect and rediscover |
| `GET` | `/v1/admin/mcp-servers/{id}/tools` | List discovered tools |

## Testing Connections

You can test connectivity to an MCP server without affecting the live connection. The test performs an ephemeral connect, lists available tools, and disconnects.

**API:**

```bash
curl -X POST http://localhost:8000/v1/admin/mcp-servers/{id}/test \
  -H "Authorization: Bearer $TOKEN"
```

Response (always HTTP 200):

```json
{
  "success": true,
  "tool_count": 3,
  "tools": [
    {"name": "my_tool", "description": "Does something"}
  ],
  "error": null,
  "error_code": null
}
```

On failure, `success` is `false` and `error_code` is one of: `connection_error`, `timeout`, `auth_error`, or `config_error`.

**Dashboard:** Click the network check icon in the actions column of any server row. The result appears inline below the server name.

## Tool Priority

MCP tools have the lowest priority. If a code tool or file tool has the same name, it takes precedence:

1. **Code tools** (highest) -- registered via `@gw.tool()` or `gw.tool()`
2. **File tools** -- defined in workspace YAML files
3. **MCP tools** (lowest) -- discovered from MCP servers

## Example

See `examples/test-project/` for a complete working example with:

- `mcp_test_server.py` -- a FastMCP server providing utility tools
- `app.py` -- registers the server via `gw.add_mcp_server()`
- `workspace/agents/assistant/AGENT.md` -- assigns `mcp_servers: [test-tools]`
