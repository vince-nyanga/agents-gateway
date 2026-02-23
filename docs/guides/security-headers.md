# Security Headers

Security headers protect your application against common browser-based attacks such as cross-site scripting (XSS), clickjacking, and MIME-type sniffing. Agent Gateway injects standard security headers into every HTTP response by default -- no configuration required.

## Configuration via `gateway.yaml`

```yaml
security:
  enabled: true                          # Enabled by default (set false to disable)
  x_content_type_options: "nosniff"
  x_frame_options: "DENY"
  strict_transport_security: "max-age=31536000; includeSubDomains"
  content_security_policy: "default-src 'self'"
  referrer_policy: "strict-origin-when-cross-origin"
```

| Field | Default | Description |
|---|---|---|
| `enabled` | `true` | Master switch. Set to `false` to disable all security headers. |
| `x_content_type_options` | `"nosniff"` | Prevents browsers from MIME-sniffing the response content type. |
| `x_frame_options` | `"DENY"` | Controls whether the page can be embedded in iframes. `DENY` blocks all framing; `SAMEORIGIN` allows same-origin framing. |
| `strict_transport_security` | `"max-age=31536000; includeSubDomains"` | Instructs browsers to only connect via HTTPS. Set to `""` to disable (useful for local development without TLS). |
| `content_security_policy` | `"default-src 'self'"` | Restricts the sources from which content can be loaded. Applied to all API responses. |
| `referrer_policy` | `"strict-origin-when-cross-origin"` | Controls how much referrer information is sent with requests. |

## Fluent API

You can customize security headers directly on the gateway instance:

```python
from agent_gateway import Gateway

gw = Gateway()
gw.use_security_headers(
    x_frame_options="SAMEORIGIN",
    content_security_policy="default-src 'self'; script-src 'self'",
)
```

Values provided via the fluent API take precedence over anything set in `gateway.yaml`.

## Default Behavior

Unlike CORS and rate limiting, security headers are **enabled by default**. Every HTTP response includes the five headers listed above without any configuration. This provides out-of-the-box protection for production deployments.

## Dashboard CSP

The built-in dashboard requires inline styles and scripts to render correctly. Agent Gateway automatically applies a relaxed Content-Security-Policy to paths under `/dashboard/`:

```
default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:
```

API paths continue to receive the strict CSP (`default-src 'self'` by default). You can customize the dashboard CSP via the `dashboard_content_security_policy` field in `gateway.yaml` or the fluent API:

```python
gw.use_security_headers(
    dashboard_content_security_policy="default-src 'self'; style-src 'self' 'unsafe-inline'"
)
```

## Disabling

If your reverse proxy (Nginx, Caddy, Cloudflare) already sets security headers, disable the gateway's headers to avoid duplicates:

```yaml
security:
  enabled: false
```

## Common Patterns

### Production behind Nginx

Let Nginx handle HSTS and disable it in the gateway to avoid duplicate headers:

```yaml
security:
  enabled: true
  strict_transport_security: ""  # Nginx handles HSTS
```

### Embedding in iframes

If your API responses need to be embedded in same-origin iframes:

```yaml
security:
  enabled: true
  x_frame_options: "SAMEORIGIN"
```

### Local development without TLS

HSTS can cause issues when developing locally without HTTPS. Disable it while keeping other headers active:

```yaml
security:
  enabled: true
  strict_transport_security: ""
```
