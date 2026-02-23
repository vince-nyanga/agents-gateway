# OpenAPI Documentation

Agent Gateway generates a fully documented OpenAPI schema out of the box. Every built-in endpoint has a summary, description, tag, and error response definitions, so the interactive API docs at `/docs` (Swagger UI) and `/redoc` are immediately useful without any extra configuration.

## Interactive Docs

Once your gateway is running, open:

- **`/docs`** — Swagger UI, with try-it-out support
- **`/redoc`** — ReDoc, optimised for reading

Both UIs are enabled by default. To disable or move them, pass `docs_url` or `redoc_url` via `fastapi_kwargs`:

```python
gw = Gateway(
    workspace="./workspace",
    docs_url=None,       # disable Swagger UI
    redoc_url="/api-docs",
)
```

## Tag Groups

All built-in routes are organised into 11 tag groups. These appear as collapsible sections in Swagger UI and ReDoc:

| Tag | Endpoints |
|-----|-----------|
| **Health** | `GET /v1/health` |
| **Agents** | List agents, get agent, invoke agent |
| **Chat** | `POST /v1/agents/{id}/chat` |
| **Sessions** | Session CRUD |
| **Conversations** | Persistent conversation history |
| **Executions** | List, get, cancel, workflow tree |
| **Schedules** | List, get, pause, resume, trigger |
| **Tools** | List and get tools |
| **Skills** | List and get skills |
| **User Config** | Per-user agent config CRUD, setup schema |
| **Admin** | Workspace reload, memory compaction |

## Adding Custom Tags

If you add your own routes to the gateway, pass `openapi_tags` in the constructor. Your tags are merged with the built-in ones (de-duplicated by name):

```python
from agent_gateway import Gateway

gw = Gateway(
    workspace="./workspace",
    openapi_tags=[
        {
            "name": "Webhooks",
            "description": "Inbound webhook handlers for third-party integrations.",
        },
    ],
)

@gw.post("/v1/webhooks/github", tags=["Webhooks"])
async def github_webhook(payload: dict):
    ...
```

Your tag descriptions appear in Swagger UI alongside the built-in groups.

## The `build_responses` Helper

When writing custom routes that should match the same error-response style as built-in endpoints, use the `build_responses` helper from `agent_gateway.api.openapi`:

```python
from agent_gateway.api.openapi import build_responses

@gw.get(
    "/v1/reports/{report_id}",
    tags=["Reports"],
    summary="Get a report",
    responses=build_responses(auth=True, not_found=True),
)
async def get_report(report_id: str):
    ...
```

`build_responses` accepts keyword flags and returns a `responses` dict ready for FastAPI's route decorator:

| Flag | Status codes added |
|------|--------------------|
| `auth=True` | `401 Authentication required`, `403 Insufficient permissions` |
| `not_found=True` | `404 Resource not found` |
| `conflict=True` | `409 Conflict — invalid state transition` |
| `rate_limit=True` | `429 Rate limit exceeded` |

All error bodies use the standard `ErrorResponse` schema (same as built-in endpoints), so clients get a consistent response structure across the whole API.

```python
from agent_gateway.api.openapi import build_responses

responses = build_responses(auth=True, not_found=True, rate_limit=True)
# {
#   401: {"description": "Authentication required", "model": ErrorResponse},
#   403: {"description": "Insufficient permissions", "model": ErrorResponse},
#   404: {"description": "Resource not found", "model": ErrorResponse},
#   429: {"description": "Rate limit exceeded", "model": ErrorResponse},
# }
```

You can merge additional status codes into the result before passing it to the decorator:

```python
responses = build_responses(auth=True) | {
    200: {"description": "Report returned successfully"},
    202: {"description": "Report generation queued"},
}
```
