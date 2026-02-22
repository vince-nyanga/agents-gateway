"""Tests for UserAgentConfig domain model and repository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_gateway.persistence.domain import UserAgentConfig
from agent_gateway.persistence.null import NullUserAgentConfigRepository


class TestUserAgentConfigModel:
    """Test the UserAgentConfig dataclass."""

    def test_defaults(self) -> None:
        config = UserAgentConfig(user_id="user-1", agent_id="agent-1")
        assert config.instructions is None
        assert config.config_values == {}
        assert config.encrypted_secrets == {}
        assert config.setup_completed is False

    def test_with_values(self) -> None:
        config = UserAgentConfig(
            user_id="user-1",
            agent_id="agent-1",
            instructions="Be formal",
            config_values={"topic": "tech"},
            encrypted_secrets={"api_key": "encrypted_value"},
            setup_completed=True,
        )
        assert config.instructions == "Be formal"
        assert config.config_values["topic"] == "tech"
        assert config.setup_completed is True


class TestNullUserAgentConfigRepository:
    """Test the null implementation."""

    @pytest.fixture
    def repo(self) -> NullUserAgentConfigRepository:
        return NullUserAgentConfigRepository()

    async def test_get_returns_none(self, repo: NullUserAgentConfigRepository) -> None:
        result = await repo.get("user", "agent")
        assert result is None

    async def test_upsert_is_noop(self, repo: NullUserAgentConfigRepository) -> None:
        config = UserAgentConfig(user_id="u", agent_id="a")
        await repo.upsert(config)  # should not raise

    async def test_delete_returns_false(self, repo: NullUserAgentConfigRepository) -> None:
        assert await repo.delete("u", "a") is False

    async def test_list_by_user_returns_empty(self, repo: NullUserAgentConfigRepository) -> None:
        assert await repo.list_by_user("u") == []

    async def test_list_by_agent_returns_empty(self, repo: NullUserAgentConfigRepository) -> None:
        assert await repo.list_by_agent("a") == []


class TestUserAgentConfigSqlRepository:
    """Test SQL repository with in-memory SQLite."""

    @pytest.fixture
    async def repo(self):
        """Create an in-memory SQLite backend and return the user_agent_config repo."""
        from agent_gateway.persistence.backends.sqlite import SqliteBackend

        backend = SqliteBackend(path=":memory:")
        await backend.initialize()
        yield backend.user_agent_config_repo
        await backend.dispose()

    async def test_upsert_and_get(self, repo) -> None:
        now = datetime.now(UTC)
        config = UserAgentConfig(
            user_id="user-1",
            agent_id="agent-1",
            instructions="Be concise",
            config_values={"format": "brief"},
            encrypted_secrets={"key": "encrypted"},
            setup_completed=True,
            created_at=now,
            updated_at=now,
        )
        await repo.upsert(config)
        result = await repo.get("user-1", "agent-1")
        assert result is not None
        assert result.instructions == "Be concise"
        assert result.config_values == {"format": "brief"}
        assert result.setup_completed is True

    async def test_upsert_updates_existing(self, repo) -> None:
        now = datetime.now(UTC)
        config = UserAgentConfig(
            user_id="user-1",
            agent_id="agent-1",
            instructions="V1",
            setup_completed=False,
            created_at=now,
            updated_at=now,
        )
        await repo.upsert(config)

        config.instructions = "V2"
        config.setup_completed = True
        await repo.upsert(config)

        result = await repo.get("user-1", "agent-1")
        assert result is not None
        assert result.instructions == "V2"
        assert result.setup_completed is True

    async def test_delete(self, repo) -> None:
        now = datetime.now(UTC)
        config = UserAgentConfig(
            user_id="user-1",
            agent_id="agent-1",
            created_at=now,
            updated_at=now,
        )
        await repo.upsert(config)
        assert await repo.delete("user-1", "agent-1") is True
        assert await repo.get("user-1", "agent-1") is None
        assert await repo.delete("user-1", "agent-1") is False

    async def test_list_by_user(self, repo) -> None:
        now = datetime.now(UTC)
        for agent_id in ["agent-1", "agent-2"]:
            await repo.upsert(
                UserAgentConfig(
                    user_id="user-1",
                    agent_id=agent_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        results = await repo.list_by_user("user-1")
        assert len(results) == 2

    async def test_list_by_agent(self, repo) -> None:
        now = datetime.now(UTC)
        for user_id in ["user-1", "user-2"]:
            await repo.upsert(
                UserAgentConfig(
                    user_id=user_id,
                    agent_id="agent-1",
                    created_at=now,
                    updated_at=now,
                )
            )
        results = await repo.list_by_agent("agent-1")
        assert len(results) == 2
