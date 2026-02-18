"""Tests for telemetry metrics definitions."""

from __future__ import annotations

from opentelemetry.sdk.metrics import MeterProvider

from agent_gateway.telemetry.metrics import AgentGatewayMetrics, create_metrics


def test_create_metrics_returns_all_instruments():
    """create_metrics should return a fully populated AgentGatewayMetrics."""
    provider = MeterProvider()
    meter = provider.get_meter("test")
    metrics = create_metrics(meter)

    assert isinstance(metrics, AgentGatewayMetrics)
    assert metrics.executions_total is not None
    assert metrics.executions_duration is not None
    assert metrics.llm_calls_total is not None
    assert metrics.llm_duration is not None
    assert metrics.llm_tokens_input is not None
    assert metrics.llm_tokens_output is not None
    assert metrics.llm_cost_usd is not None
    assert metrics.tools_calls_total is not None
    assert metrics.tools_duration is not None
    assert metrics.schedules_runs_total is not None


def test_create_metrics_without_meter():
    """create_metrics with no meter argument should use global meter."""
    metrics = create_metrics()
    assert isinstance(metrics, AgentGatewayMetrics)
