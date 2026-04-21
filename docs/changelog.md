# Changelog

All notable changes to Agent Gateway will be documented here.

This project follows [Semantic Versioning](https://semver.org/) and uses [Conventional Commits](https://www.conventionalcommits.org/).

## Unreleased

### Added

- **Sub-app mounting** — `Gateway.mount_to(parent, path)` lets you mount the gateway into an existing FastAPI application with full feature parity (dashboard, auth, OAuth2, static assets, scheduling, MCP, and chat streaming). See the [Sub-App Mounting guide](guides/mounting.md).
- **Output schema on `AgentDefinition`** — agents can declare `output_schema` in `AGENT.md` frontmatter or register a Pydantic model via `gw.set_output_schema()`. Every `invoke` call and scheduled run automatically constrains the LLM to produce JSON matching the schema and validates the response. Caller-provided `options.output_schema` still wins per-request. Chat endpoints are intentionally exempt. See the [Structured Output guide](guides/structured-output.md).
- **Per-agent typed invoke routes in OpenAPI** — agents with an `input_schema` or `output_schema` now surface a dedicated typed operation (`POST /v1/agents/<id>/invoke`) in `/openapi.json`, so Swagger UI and generated clients see per-agent request and response shapes. FastAPI performs framework-level request validation with a backwards-compatible `input_validation_failed` 422 envelope (plus a new `error.details` array). Schemaless agents fall through to the existing generic parameterized route. See the [OpenAPI guide](guides/openapi.md) and [Structured Output guide](guides/structured-output.md).
- **HTTPS reverse-proxy support** — new `Gateway.use_proxy_headers(trust_forwarded=True, forwarded_allow_ips=...)` fluent method installs Uvicorn's `ProxyHeadersMiddleware` so `request.url_for()` and session cookie hardening respect the external HTTPS URL. Five new session-cookie kwargs on `use_dashboard` / `DashboardAuthConfig` (`session_cookie_https_only`, `session_cookie_same_site`, `session_cookie_name`, `session_cookie_domain`, `session_max_age_seconds`) let operators mark the cookie `Secure` under HTTPS. See the new [Running Behind an HTTPS Reverse Proxy](guides/mounting.md#running-behind-an-https-reverse-proxy) section.
- **`use_dashboard(session_secret=...)`** — pin the dashboard session cookie signing key via the fluent API (same effect as `AGENT_GATEWAY_DASHBOARD__AUTH__SESSION_SECRET`). **Required for multi-instance deployments** (ECS/Fargate, Kubernetes replicas) where each pod otherwise auto-generates its own key and cookies signed by one pod cannot be verified by another.

### Fixed

- **Mounted gateway OAuth2 redirect_uri points to internal host** — OAuth2 authorize / callback now construct `redirect_uri` from the external URL when `use_proxy_headers(trust_forwarded=True)` is enabled (or Uvicorn is launched with `--proxy-headers`). A belt-and-braces forwarded-header rewrite is applied only when proxy trust is on, preventing header-injection hijacks on untrusted upstreams.
- **Dashboard session cookie dropped by strict intermediaries on HTTPS** — when running behind an HTTPS proxy with `trust_forwarded` on, the session cookie's `Secure` attribute is auto-enabled, restoring login on Cloudflare Access / Zscaler / HTTPS-only browser modes.
- **Dashboard chat streaming hangs when the session expires** — the streaming chat `fetch()` now sets `redirect: 'error'` and `Accept: text/event-stream`, and verifies the response `Content-Type` on arrival. If the server tries to 302 the request to `/dashboard/login` (expired session) or returns HTML, the client navigates to the login page immediately rather than silently spinning while parsing HTML as an SSE stream.
- **SSE response headers now defeat Cloudflare / GCP-LB buffering** — the chat `StreamingResponse` returns `Cache-Control: no-cache, no-transform` and drops the obsolete `Connection: keep-alive` hop-by-hop header. `X-Accel-Buffering: no` is preserved.

See the [GitHub Releases](https://github.com/vince-nyanga/agents-gateway/releases) page for the latest changes.
