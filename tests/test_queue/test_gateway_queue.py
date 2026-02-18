"""Tests for Gateway queue fluent API and lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_gateway.gateway import Gateway
from agent_gateway.queue.backends.memory import MemoryQueue
from agent_gateway.queue.null import NullQueue


def test_use_memory_queue_returns_gateway(tmp_path: Path) -> None:
    """use_memory_queue returns the gateway for chaining."""
    gw = Gateway(workspace=str(tmp_path))
    result = gw.use_memory_queue()
    assert result is gw
    assert isinstance(gw._queue_backend, MemoryQueue)


def test_use_queue_none_clears_backend(tmp_path: Path) -> None:
    """use_queue(None) sets backend to None."""
    gw = Gateway(workspace=str(tmp_path))
    gw.use_memory_queue()
    gw.use_queue(None)
    assert gw._queue_backend is None


def test_fluent_methods_reject_after_started(tmp_path: Path) -> None:
    """Fluent methods raise RuntimeError after gateway has started."""
    gw = Gateway(workspace=str(tmp_path))
    gw._started = True

    with pytest.raises(RuntimeError, match="Cannot configure queue"):
        gw.use_memory_queue()

    with pytest.raises(RuntimeError, match="Cannot configure queue"):
        gw.use_redis_queue()

    with pytest.raises(RuntimeError, match="Cannot configure queue"):
        gw.use_rabbitmq_queue()

    with pytest.raises(RuntimeError, match="Cannot configure queue"):
        gw.use_queue(None)


async def test_gateway_initializes_memory_queue(tmp_path: Path) -> None:
    """Gateway with use_memory_queue initializes queue during startup."""
    # Create minimal workspace
    (tmp_path / "agents").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()

    gw = Gateway(workspace=str(tmp_path), auth=False)
    gw.use_memory_queue()

    async with gw:
        assert isinstance(gw._queue, MemoryQueue)
        assert gw._worker_pool is not None

    # After shutdown, queue should be NullQueue
    assert isinstance(gw._queue, NullQueue)


async def test_gateway_default_no_queue(tmp_path: Path) -> None:
    """Gateway without queue config uses NullQueue."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()

    gw = Gateway(workspace=str(tmp_path), auth=False)

    async with gw:
        assert isinstance(gw._queue, NullQueue)
        assert gw._worker_pool is None
