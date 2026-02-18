"""Chat session model and in-memory store with TTL and LRU eviction."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes
DEFAULT_MAX_SESSIONS = 1000
DEFAULT_MAX_HISTORY = 100
MAX_METADATA_SIZE = 64 * 1024  # 64KB


@dataclass
class ChatSession:
    """A multi-turn chat session with an agent."""

    session_id: str
    agent_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: datetime.now(UTC).timestamp())
    updated_at: float = field(default_factory=lambda: datetime.now(UTC).timestamp())
    metadata: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # Internal monotonic timestamp for TTL checks
    _last_active: float = field(default_factory=time.monotonic, repr=False)

    @property
    def turn_count(self) -> int:
        """Number of user messages in this session."""
        return sum(1 for m in self.messages if m.get("role") == "user")

    def _touch(self) -> None:
        """Update timestamps."""
        self.updated_at = datetime.now(UTC).timestamp()
        self._last_active = time.monotonic()

    def append_user_message(self, content: str) -> None:
        """Add a user message and update timestamp."""
        self.messages.append({"role": "user", "content": content})
        self._touch()

    def append_assistant_message(
        self,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add an assistant message and update timestamp."""
        msg: dict[str, Any] = {"role": "assistant"}
        if content is not None:
            msg["content"] = content
        if tool_calls is not None:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        self._touch()

    def truncate_history(self, max_messages: int) -> None:
        """Keep only the most recent messages, preserving tool-call sequences.

        Finds a safe truncation point that doesn't split an assistant message
        with tool_calls from its corresponding tool result messages.
        """
        if len(self.messages) <= max_messages:
            return

        # Start from the desired cut point and scan forward to find a safe boundary
        cut_index = len(self.messages) - max_messages
        while cut_index < len(self.messages):
            msg = self.messages[cut_index]
            # A tool result message without its preceding assistant+tool_calls is invalid
            if msg.get("role") == "tool":
                cut_index += 1
                continue
            # An assistant message with tool_calls needs its tool results after it
            # Check the message *before* cut_index: if it's an assistant with tool_calls,
            # we'd be cutting its tool results. But since we're starting at cut_index,
            # we only care that cut_index itself is a safe start.
            break

        self.messages = self.messages[cut_index:]

    def merge_metadata(self, context: dict[str, Any]) -> None:
        """Merge context into session metadata, respecting size limits."""
        import json

        # Estimate current size
        merged = {**self.metadata, **context}
        try:
            size = len(json.dumps(merged))
        except (TypeError, ValueError):
            size = 0
        if size > MAX_METADATA_SIZE:
            logger.warning(
                "Session %s metadata exceeds %dKB limit, skipping merge",
                self.session_id,
                MAX_METADATA_SIZE // 1024,
            )
            return
        self.metadata = merged


class SessionStore:
    """In-memory session store with TTL expiry and LRU eviction."""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._max_history = max_history
        self._sessions: OrderedDict[str, ChatSession] = OrderedDict()

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def create_session(
        self,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ChatSession:
        """Create a new chat session. Evicts LRU if at capacity."""
        # Evict oldest if at capacity
        while len(self._sessions) >= self._max_sessions:
            evicted_id, _ = self._sessions.popitem(last=False)
            logger.info("Evicted LRU session: %s", evicted_id)

        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = ChatSession(
            session_id=session_id,
            agent_id=agent_id,
            metadata=metadata or {},
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        """Get a session by ID. Moves it to end of LRU order."""
        session = self._sessions.get(session_id)
        if session is None:
            return None

        # Check TTL
        if self._is_expired(session):
            del self._sessions[session_id]
            return None

        # Move to end (most recently used)
        self._sessions.move_to_end(session_id)
        return session

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def list_sessions(
        self,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[ChatSession]:
        """List sessions, optionally filtered by agent_id."""
        results: list[ChatSession] = []
        for session in reversed(self._sessions.values()):
            if self._is_expired(session):
                continue
            if agent_id and session.agent_id != agent_id:
                continue
            results.append(session)
            if len(results) >= limit:
                break
        return results

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count of removed sessions."""
        expired = [sid for sid, s in self._sessions.items() if self._is_expired(s)]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            logger.info("Cleaned up %d expired sessions", len(expired))
        return len(expired)

    def _is_expired(self, session: ChatSession) -> bool:
        return (time.monotonic() - session._last_active) > self._ttl_seconds
