"""Tests for ChatSession and SessionStore."""

from __future__ import annotations

import asyncio
import time

from agent_gateway.chat.session import ChatSession, SessionStore


class TestChatSession:
    """Tests for the ChatSession dataclass."""

    def test_create_session(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        assert session.session_id == "sess_1"
        assert session.agent_id == "test-agent"
        assert session.messages == []
        assert session.turn_count == 0

    def test_append_user_message(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        session.append_user_message("hello")
        assert len(session.messages) == 1
        assert session.messages[0] == {"role": "user", "content": "hello"}
        assert session.turn_count == 1

    def test_append_assistant_message(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        session.append_assistant_message(content="hi there")
        assert len(session.messages) == 1
        assert session.messages[0] == {"role": "assistant", "content": "hi there"}
        assert session.turn_count == 0  # only user messages count

    def test_append_assistant_with_tool_calls(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        tool_calls = [{"id": "tc1", "function": {"name": "echo", "arguments": "{}"}}]
        session.append_assistant_message(tool_calls=tool_calls)
        assert session.messages[0]["tool_calls"] == tool_calls
        assert "content" not in session.messages[0]

    def test_turn_count(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        session.append_user_message("msg1")
        session.append_assistant_message(content="reply1")
        session.append_user_message("msg2")
        assert session.turn_count == 2

    def test_truncate_history(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        for i in range(10):
            session.append_user_message(f"msg{i}")
        assert len(session.messages) == 10
        session.truncate_history(5)
        assert len(session.messages) == 5
        assert session.messages[0]["content"] == "msg5"

    def test_truncate_noop_when_under_limit(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        session.append_user_message("hello")
        session.truncate_history(100)
        assert len(session.messages) == 1

    def test_truncate_preserves_tool_call_sequences(self) -> None:
        """Truncation should not split tool_call/tool_result pairs."""
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        # Build: user, assistant+tool_calls, tool, user, assistant
        session.append_user_message("msg1")
        session.append_assistant_message(
            tool_calls=[{"id": "tc1", "function": {"name": "echo", "arguments": "{}"}}]
        )
        session.messages.append(
            {
                "role": "tool",
                "tool_call_id": "tc1",
                "content": '{"result": "ok"}',
            }
        )
        session.append_user_message("msg2")
        session.append_assistant_message(content="reply")
        # 5 messages total, truncate to 3 — naive slice would start at tool result
        session.truncate_history(3)
        # Should skip the orphaned tool result and start at next user message
        assert session.messages[0]["role"] == "user"
        assert session.messages[0]["content"] == "msg2"

    def test_updated_at_changes(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        initial = session.updated_at
        time.sleep(0.01)
        session.append_user_message("hello")
        assert session.updated_at > initial

    def test_timestamps_are_wall_clock(self) -> None:
        """Timestamps should be Unix epoch seconds, not monotonic."""
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        # Wall-clock timestamps should be large (> year 2020 in epoch seconds)
        assert session.created_at > 1_577_836_800  # 2020-01-01
        assert session.updated_at > 1_577_836_800

    def test_merge_metadata(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        session.merge_metadata({"key1": "val1"})
        assert session.metadata == {"key1": "val1"}
        session.merge_metadata({"key2": "val2"})
        assert session.metadata == {"key1": "val1", "key2": "val2"}

    def test_merge_metadata_rejects_oversized(self) -> None:
        session = ChatSession(session_id="sess_1", agent_id="test-agent")
        # Try to merge something over 64KB
        big_value = "x" * 70_000
        session.merge_metadata({"big": big_value})
        # Should be rejected — metadata stays empty
        assert session.metadata == {}


class TestSessionStore:
    """Tests for the SessionStore."""

    def test_create_and_get(self) -> None:
        store = SessionStore()
        session = store.create_session("test-agent")
        assert session.session_id.startswith("sess_")
        assert session.agent_id == "test-agent"

        retrieved = store.get_session(session.session_id)
        assert retrieved is session

    def test_get_nonexistent(self) -> None:
        store = SessionStore()
        assert store.get_session("nonexistent") is None

    def test_delete(self) -> None:
        store = SessionStore()
        session = store.create_session("test-agent")
        assert store.delete_session(session.session_id) is True
        assert store.get_session(session.session_id) is None
        assert store.delete_session(session.session_id) is False

    def test_list_sessions(self) -> None:
        store = SessionStore()
        store.create_session("agent-a")
        store.create_session("agent-b")
        store.create_session("agent-a")

        all_sessions = store.list_sessions()
        assert len(all_sessions) == 3

        filtered = store.list_sessions(agent_id="agent-a")
        assert len(filtered) == 2
        assert all(s.agent_id == "agent-a" for s in filtered)

    def test_list_with_limit(self) -> None:
        store = SessionStore()
        for _ in range(5):
            store.create_session("test-agent")
        sessions = store.list_sessions(limit=2)
        assert len(sessions) == 2

    def test_max_sessions_eviction(self) -> None:
        store = SessionStore(max_sessions=3)
        s1 = store.create_session("agent")
        store.create_session("agent")
        store.create_session("agent")
        assert store.session_count == 3

        s4 = store.create_session("agent")  # noqa: F841
        assert store.session_count == 3
        # s1 should have been evicted (LRU)
        assert store.get_session(s1.session_id) is None

    def test_ttl_expiry(self) -> None:
        store = SessionStore(ttl_seconds=0.05)
        session = store.create_session("test-agent")
        assert store.get_session(session.session_id) is not None

        time.sleep(0.1)
        assert store.get_session(session.session_id) is None

    def test_cleanup_expired(self) -> None:
        store = SessionStore(ttl_seconds=0.05)
        store.create_session("agent")
        store.create_session("agent")
        assert store.session_count == 2

        time.sleep(0.1)
        removed = store.cleanup_expired()
        assert removed == 2
        assert store.session_count == 0

    def test_lru_ordering(self) -> None:
        store = SessionStore(max_sessions=3)
        s1 = store.create_session("agent")
        s2 = store.create_session("agent")
        store.create_session("agent")

        # Access s1 to move it to end
        store.get_session(s1.session_id)

        # Add s4 — should evict s2 (least recently used now)
        store.create_session("agent")
        assert store.get_session(s2.session_id) is None
        assert store.get_session(s1.session_id) is not None

    def test_create_with_metadata(self) -> None:
        store = SessionStore()
        session = store.create_session("agent", metadata={"key": "value"})
        assert session.metadata == {"key": "value"}

    def test_session_has_lock(self) -> None:
        store = SessionStore()
        session = store.create_session("agent")
        assert isinstance(session.lock, asyncio.Lock)
