"""Tests for the lifecycle hook registry."""

from __future__ import annotations

import pytest

from agent_gateway.hooks import HookRegistry


class TestHookRegistry:
    def test_register_valid_event(self) -> None:
        registry = HookRegistry()
        called = False

        async def hook(**kw):
            nonlocal called
            called = True

        registry.register("gateway.startup", hook)
        # No error raised

    def test_register_invalid_event_raises(self) -> None:
        registry = HookRegistry()

        async def hook(**kw):
            pass

        with pytest.raises(ValueError, match="Unknown hook event"):
            registry.register("invalid.event", hook)

    @pytest.mark.asyncio
    async def test_fire_calls_registered_hooks(self) -> None:
        registry = HookRegistry()
        calls: list[dict] = []

        async def hook_a(**kw):
            calls.append({"fn": "a", **kw})

        async def hook_b(**kw):
            calls.append({"fn": "b", **kw})

        registry.register("gateway.startup", hook_a)
        registry.register("gateway.startup", hook_b)

        await registry.fire("gateway.startup")

        assert len(calls) == 2
        assert calls[0]["fn"] == "a"
        assert calls[1]["fn"] == "b"

    @pytest.mark.asyncio
    async def test_fire_passes_kwargs(self) -> None:
        registry = HookRegistry()
        received: dict = {}

        async def hook(**kw):
            received.update(kw)

        registry.register("agent.invoke.before", hook)
        await registry.fire("agent.invoke.before", agent_id="test", message="hi")

        assert received["agent_id"] == "test"
        assert received["message"] == "hi"

    @pytest.mark.asyncio
    async def test_fire_unregistered_event_is_noop(self) -> None:
        registry = HookRegistry()
        # Should not raise
        await registry.fire("gateway.startup")

    @pytest.mark.asyncio
    async def test_fire_continues_after_hook_failure(self) -> None:
        registry = HookRegistry()
        calls: list[str] = []

        async def bad_hook(**kw):
            raise RuntimeError("boom")

        async def good_hook(**kw):
            calls.append("ok")

        registry.register("gateway.startup", bad_hook)
        registry.register("gateway.startup", good_hook)

        await registry.fire("gateway.startup")

        assert calls == ["ok"]

    @pytest.mark.asyncio
    async def test_multiple_events_independent(self) -> None:
        registry = HookRegistry()
        startup_calls: list[str] = []
        shutdown_calls: list[str] = []

        async def on_startup(**kw):
            startup_calls.append("start")

        async def on_shutdown(**kw):
            shutdown_calls.append("stop")

        registry.register("gateway.startup", on_startup)
        registry.register("gateway.shutdown", on_shutdown)

        await registry.fire("gateway.startup")
        assert startup_calls == ["start"]
        assert shutdown_calls == []

        await registry.fire("gateway.shutdown")
        assert shutdown_calls == ["stop"]
