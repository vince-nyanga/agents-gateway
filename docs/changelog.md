# Changelog

All notable changes to Agent Gateway will be documented here.

This project follows [Semantic Versioning](https://semver.org/) and uses [Conventional Commits](https://www.conventionalcommits.org/).

## Unreleased

### Added

- **Sub-app mounting** — `Gateway.mount_to(parent, path)` lets you mount the gateway into an existing FastAPI application with full feature parity (dashboard, auth, OAuth2, static assets, scheduling, MCP, and chat streaming). See the [Sub-App Mounting guide](guides/mounting.md).
- **Output schema on `AgentDefinition`** — agents can declare `output_schema` in `AGENT.md` frontmatter or register a Pydantic model via `gw.set_output_schema()`. Every `invoke` call and scheduled run automatically constrains the LLM to produce JSON matching the schema and validates the response. Caller-provided `options.output_schema` still wins per-request. Chat endpoints are intentionally exempt. See the [Structured Output guide](guides/structured-output.md).

See the [GitHub Releases](https://github.com/vince-nyanga/agents-gateway/releases) page for the latest changes.
