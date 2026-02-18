"""Lifecycle hook registry for Agent Gateway."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

HookFn = Callable[..., Coroutine[Any, Any, None]]

VALID_EVENTS = frozenset(
    {
        "agent.invoke.before",
        "agent.invoke.after",
        "tool.execute.before",
        "tool.execute.after",
        "llm.call.before",
        "llm.call.after",
        "gateway.startup",
        "gateway.shutdown",
    }
)


class HookRegistry:
    """Registry for lifecycle hook callbacks."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = defaultdict(list)

    def register(self, event: str, fn: HookFn) -> None:
        """Register a callback for an event."""
        if event not in VALID_EVENTS:
            raise ValueError(f"Unknown hook event: '{event}'. Valid: {sorted(VALID_EVENTS)}")
        self._hooks[event].append(fn)

    async def fire(self, event: str, **kwargs: Any) -> None:
        """Fire all callbacks registered for an event."""
        for fn in self._hooks.get(event, []):
            try:
                await fn(**kwargs)
            except Exception:
                logger.warning("Hook %s for event '%s' failed", fn.__name__, event, exc_info=True)
