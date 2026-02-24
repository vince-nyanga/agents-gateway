"""Tests for gateway configuration."""

from __future__ import annotations

import os
from pathlib import Path

from agent_gateway.config import GatewayConfig


class TestGatewayConfig:
    def test_default_config(self) -> None:
        config = GatewayConfig()
        assert config.server.port == 8000
        assert config.model.default == "gemini/gemini-2.5-flash"
        assert config.guardrails.max_iterations == 10
        assert config.guardrails.max_tool_calls == 20
        assert config.guardrails.timeout_ms == 60_000

    def test_load_from_yaml(self, fixture_workspace: Path) -> None:
        config = GatewayConfig.load(fixture_workspace)
        assert config.server.host == "127.0.0.1"
        assert config.auth.enabled is False
        assert config.persistence.enabled is False

    def test_load_missing_yaml(self, tmp_path: Path) -> None:
        config = GatewayConfig.load(tmp_path)
        assert config.server.port == 8000  # defaults

    def test_env_override(self, monkeypatch: object) -> None:
        os.environ["AGENT_GATEWAY_SERVER__PORT"] = "9000"
        try:
            config = GatewayConfig()
            assert config.server.port == 9000
        finally:
            del os.environ["AGENT_GATEWAY_SERVER__PORT"]


class TestModelConfig:
    def test_defaults(self) -> None:
        config = GatewayConfig()
        assert config.model.temperature == 0.1
        assert config.model.max_tokens == 4096
        assert config.model.fallback is None


class TestGuardrailsConfig:
    def test_defaults(self) -> None:
        config = GatewayConfig()
        assert config.guardrails.max_tool_calls == 20
        assert config.guardrails.max_iterations == 10
        assert config.guardrails.timeout_ms == 60_000
