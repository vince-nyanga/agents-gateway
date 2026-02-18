"""Chat session model and in-memory store with TTL and LRU eviction."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes
DEFAULT_MAX_SESSIONS = 1000
DEFAULT_MAX_HISTORY = 100


@dataclass
class ChatSession:
    """A multi-turn chat session with an agent."""

    session_id: str
    agent_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def turn_count(self) -> int:
        """Number of user messages in this session."""
        return sum(1 for m in self.messages if m.get("role") == "user")

    def append_user_message(self, content: str) -> None:
        """Add a user message and update timestamp."""
        self.messages.append({"role": "user", "content": content})
        self.updated_at = time.monotonic()

    def append_assistant_message(
        self,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add an assistant message and update timestamp."""
        msg: dict[str, Any] = {"role": "assistant"}
        if content:
            msg["content"] = content
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        self.updated_at = time.monotonic()

    def append_tool_result(self, tool_call_id: str, content: str) -> None:
        """Add a tool result message."""
        self.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )
        self.updated_at = time.monotonic()

    def truncate_history(self, max_messages: int) -> None:
        """Keep only the most recent messages, preserving system messages."""
        if len(self.messages) <= max_messages:
            return
        # Keep the newest messages
        self.messages = self.messages[-max_messages:]


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
        expired = [
            sid for sid, s in self._sessions.items() if self._is_expired(s)
        ]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            logger.info("Cleaned up %d expired sessions", len(expired))
        return len(expired)

    def _is_expired(self, session: ChatSession) -> bool:
        return (time.monotonic() - session.updated_at) > self._ttl_seconds
