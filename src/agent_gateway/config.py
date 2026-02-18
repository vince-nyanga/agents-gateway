"""Gateway configuration with Pydantic BaseSettings.

Precedence: Environment variables > gateway.yaml > defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


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


class AuthKeyConfig(BaseModel):
    name: str
    key: str
    scopes: list[str] = Field(default_factory=lambda: ["*"])


class AuthConfig(BaseModel):
    enabled: bool = True
    mode: str = "api_key"  # api_key | custom | none
    api_keys: list[AuthKeyConfig] = Field(default_factory=list)


class SlackConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""


class TeamsConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""


class WebhookConfig(BaseModel):
    name: str
    url: str
    secret: str = ""
    events: list[str] = Field(default_factory=list)


class NotificationsConfig(BaseModel):
    slack: SlackConfig = SlackConfig()
    teams: TeamsConfig = TeamsConfig()
    webhooks: list[WebhookConfig] = Field(default_factory=list)
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
    backend: str = "memory"  # memory | redis
    url: str = "redis://localhost:6379"


class GatewayConfig(BaseSettings):
    """Root configuration for the Agent Gateway.

    Loaded from gateway.yaml, overridden by environment variables
    prefixed with AGENT_GATEWAY_.
    """

    model_config = {"env_prefix": "AGENT_GATEWAY_", "env_nested_delimiter": "__"}

    server: ServerConfig = ServerConfig()
    model: ModelConfig = ModelConfig()
    guardrails: GuardrailsConfig = GuardrailsConfig()
    auth: AuthConfig = AuthConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    persistence: PersistenceConfig = PersistenceConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    queue: QueueConfig = QueueConfig()
    context: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> GatewayConfig:
        """Load config from a YAML file, with defaults for missing fields."""
        if not path.exists():
            return cls()
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    @classmethod
    def load(cls, workspace_path: Path) -> GatewayConfig:
        """Load config from workspace/gateway.yaml if it exists."""
        yaml_path = workspace_path / "gateway.yaml"
        return cls.from_yaml(yaml_path)
