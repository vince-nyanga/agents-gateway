"""Tests for _should_queue execution mode resolution."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.api.routes.invoke import _should_queue
from agent_gateway.workspace.agent import AgentDefinition


def _make_agent(execution_mode: str = "sync") -> AgentDefinition:
    return AgentDefinition(
        id="test-agent",
        path=Path("/tmp/test"),
        agent_prompt="You are a test agent.",
        execution_mode=execution_mode,
    )


def test_sync_agent_no_async_flag() -> None:
    """Sync agent + no async flag = inline execution."""
    agent = _make_agent("sync")
    assert _should_queue(agent, request_async=False) is False


def test_sync_agent_with_async_flag() -> None:
    """Sync agent + async flag = client escalates to queue."""
    agent = _make_agent("sync")
    assert _should_queue(agent, request_async=True) is True


def test_async_agent_no_async_flag() -> None:
    """Async agent + no flag = agent forces queuing."""
    agent = _make_agent("async")
    assert _should_queue(agent, request_async=False) is True


def test_async_agent_with_async_flag() -> None:
    """Async agent + async flag = queued."""
    agent = _make_agent("async")
    assert _should_queue(agent, request_async=True) is True


def test_default_execution_mode_is_sync() -> None:
    """Default execution mode is sync."""
    agent = AgentDefinition(
        id="test",
        path=Path("/tmp"),
        agent_prompt="prompt",
    )
    assert agent.execution_mode == "sync"
    assert _should_queue(agent, request_async=False) is False
