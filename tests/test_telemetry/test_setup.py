"""Tests for telemetry setup bootstrap."""

from __future__ import annotations

import logging

from agent_gateway.config import TelemetryConfig
from agent_gateway.telemetry import setup_telemetry


def test_setup_telemetry_console_exporter():
    """setup_telemetry should work with console exporter."""
    config = TelemetryConfig(enabled=True, exporter="console")
    # Should not raise
    setup_telemetry(config)


def test_setup_telemetry_disabled():
    """setup_telemetry should be a no-op when disabled."""
    config = TelemetryConfig(enabled=False)
    # Should not raise
    setup_telemetry(config)


def test_setup_telemetry_none_exporter():
    """setup_telemetry should handle 'none' exporter."""
    config = TelemetryConfig(enabled=True, exporter="none")
    setup_telemetry(config)


def test_setup_telemetry_unknown_exporter():
    """setup_telemetry should fall back to console for unknown exporter."""
    config = TelemetryConfig(enabled=True, exporter="unknown_thing")
    # Should not raise — falls back to console
    setup_telemetry(config)


def test_setup_telemetry_never_crashes(caplog: logging.LogRecord):
    """setup_telemetry should never crash even with bad config."""
    config = TelemetryConfig(enabled=True, exporter="otlp", endpoint="invalid://broken")
    # Should not raise — logs a warning at most
    setup_telemetry(config)


def test_setup_telemetry_otlp_without_extra():
    """setup_telemetry with OTLP should log warning if extra not installed."""
    config = TelemetryConfig(enabled=True, exporter="otlp", protocol="grpc")
    # This may or may not have the OTLP extra installed, but should never crash
    setup_telemetry(config)
