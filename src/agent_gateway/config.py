"""Gateway configuration with Pydantic BaseSettings.

Precedence: Environment variables > gateway.yaml > defaults.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _validate_timezone(tz: str) -> None:
    """Validate that a timezone string is a valid IANA timezone name."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, KeyError) as e:
        raise ValueError(
            f"Invalid timezone '{tz}'. Must be a valid IANA timezone name "
            f"(e.g., 'UTC', 'Europe/London', 'America/New_York')."
        ) from e


def _resolve_env_vars(data: Any) -> Any:
    """Recursively resolve ${VAR} placeholders from environment.

    Raises ValueError if a referenced variable is undefined.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = _resolve_env_vars(value)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            data[i] = _resolve_env_vars(item)
    elif isinstance(data, str):
        match = _ENV_VAR_PATTERN.search(data)
        if match:
            var_name = match.group(1)
            var_value = os.environ.get(var_name)
            if var_value is None:
                raise ValueError(
                    f"Environment variable '${{{var_name}}}' is not defined. "
                    f"Set it or remove the reference from gateway.yaml."
                )
            # Full replacement if the entire string is a single ${VAR}
            if match.group(0) == data:
                return var_value

            # Partial replacement for embedded vars
            def _replace(m: re.Match[str]) -> str:
                name = m.group(1)
                val = os.environ.get(name)
                if val is None:
                    raise ValueError(
                        f"Environment variable '${{{name}}}' is not defined. "
                        f"Set it or remove the reference from gateway.yaml."
                    )
                return val

            return _ENV_VAR_PATTERN.sub(_replace, data)
    return data


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1


class ModelConfig(BaseModel):
    default: str = "gpt-4o-mini"
    temperature: float = 0.1
    max_tokens: int = 4096
    fallback: str | None = None


class GuardrailsConfig(BaseModel):
    max_tool_calls: int = 20
    max_iterations: int = 10
    timeout_ms: int = 60_000
    max_delegation_depth: int = 3


class AuthKeyConfig(BaseModel):
    name: str
    key: str
    scopes: list[str] = Field(default_factory=lambda: ["*"])


class OAuth2Config(BaseModel):
    issuer: str
    audience: str
    jwks_uri: str | None = None
    algorithms: list[str] = Field(default_factory=lambda: ["RS256", "ES256"])
    scope_claim: str = "scope"  # "scp" for Azure AD
    clock_skew_seconds: int = 30


class AuthConfig(BaseModel):
    enabled: bool = True
    mode: str = "api_key"  # api_key | oauth2 | composite | custom | none
    api_keys: list[AuthKeyConfig] = Field(default_factory=list)
    oauth2: OAuth2Config | None = None
    public_paths: list[str] = Field(default_factory=lambda: ["/v1/health"])


class SlackConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    default_channel: str = "#agent-alerts"


class WebhookEndpointConfig(BaseModel):
    name: str
    url: str
    secret: str = ""
    events: list[str] = Field(default_factory=list)
    payload_template: str | None = None


class NotificationsConfig(BaseModel):
    slack: SlackConfig = SlackConfig()
    webhooks: list[WebhookEndpointConfig] = Field(default_factory=list)
    webhook_secret: str = ""


class PersistenceConfig(BaseModel):
    enabled: bool = True
    backend: str = "sqlite"  # sqlite | postgres
    url: str = "sqlite+aiosqlite:///agent_gateway.db"
    table_prefix: str = ""
    db_schema: str | None = None  # PostgreSQL schema name


class TelemetryConfig(BaseModel):
    enabled: bool = True
    service_name: str = "agent-gateway"
    exporter: str = "console"  # console | otlp | none
    endpoint: str = "http://localhost:4317"
    protocol: str = "grpc"  # grpc | http
    sample_rate: float = 1.0


class QueueConfig(BaseModel):
    backend: str = "none"  # none | memory | redis | rabbitmq
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    stream_key: str = "ag:executions"
    queue_name: str = "ag.executions"
    consumer_group: str = "ag-workers"
    workers: int = 4
    max_retries: int = 3
    visibility_timeout_s: int = 300
    drain_timeout_s: int = 30
    default_execution_mode: str = "sync"  # sync | async


class SchedulerConfig(BaseModel):
    enabled: bool = True
    misfire_grace_seconds: int = 60
    max_instances: int = 1
    coalesce: bool = True


class ContextRetrievalConfig(BaseModel):
    retriever_timeout_seconds: float = 10.0
    max_retrieved_chars: int = 50_000
    max_context_file_chars: int = 100_000


class CompactionConfig(BaseModel):
    """Settings for memory compaction (prevents unbounded growth)."""

    enabled: bool = True
    max_memories_per_scope: int = 100  # trigger threshold
    compact_ratio: float = 0.5  # compact oldest 50%
    min_age_hours: int = 24  # don't compact memories < 24h old
    importance_threshold: float = 0.8  # never compact importance >= 0.8
    decay_factor: float = 0.95  # relevance decay per day since last access


class MemoryConfig(BaseModel):
    """Global memory defaults (overridable per-agent in AGENT.md)."""

    enabled: bool = False
    max_injected_chars: int = 4000
    extraction_model: str | None = None
    auto_extract: bool = False
    max_memory_md_lines: int = 200
    compaction: CompactionConfig = CompactionConfig()


class DashboardOAuth2Config(BaseModel):
    issuer: str
    client_id: str
    client_secret: str  # Required — confidential client
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])


class DashboardAuthConfig(BaseModel):
    enabled: bool = True
    username: str = "admin"
    password: str = ""  # empty = no password (warned at startup)
    login_button_text: str = "Sign in with SSO"
    session_secret: str = ""  # auto-generated if empty
    oauth2: DashboardOAuth2Config | None = None


class DashboardColorConfig(BaseModel):
    primary: str = "#6366f1"
    primary_dark: str = "#818cf8"
    secondary: str = "#64748b"
    secondary_dark: str = "#94a3b8"
    accent: str = ""  # defaults to primary if empty
    accent_dark: str = ""  # defaults to primary_dark if empty
    surface: str = "#ffffff"
    surface_dark: str = "#141b2d"
    sidebar: str = "#0f172a"
    sidebar_dark: str = "#0b0f1a"
    danger: str = "#ef4444"
    danger_dark: str = "#f87171"


class DashboardThemeConfig(BaseModel):
    mode: Literal["light", "dark", "auto"] = "auto"
    accent_color: str = "#6366f1"  # legacy — maps to colors.primary
    accent_color_dark: str = "#818cf8"  # legacy — maps to colors.primary_dark
    colors: DashboardColorConfig = DashboardColorConfig()

    def resolved_colors(self) -> DashboardColorConfig:
        """Return colors with legacy accent_color mapped and defaults resolved."""
        data = self.colors.model_dump()
        # Legacy compat: accent_color overrides primary if changed from default
        if self.accent_color != "#6366f1" and data["primary"] == "#6366f1":
            data["primary"] = self.accent_color
        if self.accent_color_dark != "#818cf8" and data["primary_dark"] == "#818cf8":
            data["primary_dark"] = self.accent_color_dark
        # Accent defaults to primary
        if not data["accent"]:
            data["accent"] = data["primary"]
        if not data["accent_dark"]:
            data["accent_dark"] = data["primary_dark"]
        return DashboardColorConfig(**data)


class DashboardConfig(BaseModel):
    enabled: bool = False  # opt-in
    title: str = "Agent Gateway"
    logo_url: str | None = None
    favicon_url: str | None = None
    auth: DashboardAuthConfig = DashboardAuthConfig()
    theme: DashboardThemeConfig = DashboardThemeConfig()


class RateLimitConfig(BaseModel):
    enabled: bool = False
    default_limit: str = "100/minute"
    storage_uri: str | None = None
    trust_forwarded_for: bool = False


class SecurityConfig(BaseModel):
    enabled: bool = True  # opt-out, not opt-in
    x_content_type_options: str = "nosniff"
    x_frame_options: str = "DENY"
    strict_transport_security: str = "max-age=31536000; includeSubDomains"
    content_security_policy: str = "default-src 'self'"
    referrer_policy: str = "strict-origin-when-cross-origin"
    # Relaxed CSP for dashboard paths (needs inline styles/scripts)
    dashboard_content_security_policy: str = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self' data:"
    )


class CorsConfig(BaseModel):
    enabled: bool = False
    allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    allow_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "DELETE", "OPTIONS"])
    allow_headers: list[str] = Field(default_factory=lambda: ["Authorization", "Content-Type"])
    allow_credentials: bool = False
    max_age: int = 3600

    @model_validator(mode="after")
    def _reject_wildcard_with_credentials(self) -> CorsConfig:
        if self.allow_credentials and "*" in self.allow_origins:
            raise ValueError(
                "allow_credentials=True cannot be used with allow_origins=['*']. "
                "Specify explicit origins instead."
            )
        return self


class GatewayConfig(BaseSettings):
    """Root configuration for the Agent Gateway.

    Loaded from gateway.yaml, overridden by environment variables
    prefixed with AGENT_GATEWAY_.
    """

    model_config = {"env_prefix": "AGENT_GATEWAY_", "env_nested_delimiter": "__"}

    timezone: str = "UTC"
    server: ServerConfig = ServerConfig()
    model: ModelConfig = ModelConfig()
    guardrails: GuardrailsConfig = GuardrailsConfig()
    auth: AuthConfig = AuthConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    persistence: PersistenceConfig = PersistenceConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    queue: QueueConfig = QueueConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    context_retrieval: ContextRetrievalConfig = ContextRetrievalConfig()
    memory: MemoryConfig = MemoryConfig()
    context: dict[str, Any] = Field(default_factory=dict)
    cors: CorsConfig = CorsConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()
    security: SecurityConfig = SecurityConfig()
    dashboard: DashboardConfig = DashboardConfig()

    @classmethod
    def from_yaml(cls, path: Path) -> GatewayConfig:
        """Load config from a YAML file, with defaults for missing fields."""
        if not path.exists():
            return cls()
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        _resolve_env_vars(data)
        config = cls(**data)
        # Validate timezone is a valid IANA name
        _validate_timezone(config.timezone)
        return config

    @classmethod
    def load(cls, workspace_path: Path) -> GatewayConfig:
        """Load config from workspace/gateway.yaml if it exists."""
        yaml_path = workspace_path / "gateway.yaml"
        return cls.from_yaml(yaml_path)
