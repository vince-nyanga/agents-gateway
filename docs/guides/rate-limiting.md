# Rate Limiting

Agent Gateway supports request rate limiting via [slowapi](https://github.com/laurentS/slowapi), an optional dependency.

## Installation

```bash
pip install agents-gateway[rate-limiting]
```

## Configuration

### Via gateway.yaml

```yaml
rate_limit:
  enabled: true
  default_limit: "100/minute"
```

### Via Python API

```python
from agent_gateway import Gateway

gw = Gateway(workspace="workspace/")
gw.use_rate_limit(default_limit="50/minute")
```

Both approaches are equivalent. The `use_rate_limit()` method takes precedence over `gateway.yaml` if both are set.

## Rate limit format

Rate limits use slowapi's string format:

| Example | Meaning |
|---------|---------|
| `"10/second"` | 10 requests per second |
| `"100/minute"` | 100 requests per minute |
| `"1000/hour"` | 1000 requests per hour |
| `"10000/day"` | 10000 requests per day |

## Multi-worker deployments

By default, rate limit counters are stored in memory. With multiple workers (`server.workers > 1`), each worker tracks limits independently — a client could effectively get `N x limit` requests through.

To enforce limits across workers, point `storage_uri` at a Redis instance:

```yaml
rate_limit:
  enabled: true
  default_limit: "100/minute"
  storage_uri: "redis://localhost:6379"
```

Gateway logs a warning at startup if multiple workers are configured without a `storage_uri`.

## Reverse proxy deployments

When running behind a reverse proxy (nginx, AWS ALB, etc.), client IPs appear as the proxy address. Enable `trust_forwarded_for` to read the real client IP from the `X-Forwarded-For` header:

```yaml
rate_limit:
  enabled: true
  default_limit: "100/minute"
  trust_forwarded_for: true
```

!!! warning
    Only enable `trust_forwarded_for` when you trust the proxy setting the header. Untrusted clients can spoof this header to bypass rate limits.

## Response headers

When rate limiting is enabled, responses include standard rate limit headers:

- `X-RateLimit-Limit` — the configured limit
- `X-RateLimit-Remaining` — requests remaining in the current window
- `X-RateLimit-Reset` — seconds until the window resets

When a client exceeds the limit, they receive a `429 Too Many Requests` response:

```json
{"detail": "Rate limit exceeded"}
```
