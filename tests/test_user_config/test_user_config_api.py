"""Tests for per-user agent configuration API routes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.gateway import Gateway
from agent_gateway.persistence.domain import UserAgentConfig

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURE_WORKSPACE = FIXTURES_DIR / "workspace"


def _make_gateway(**overrides: Any) -> Gateway:
    """Create a test gateway with auth disabled."""
    return Gateway(
        workspace=str(FIXTURE_WORKSPACE),
        auth=False,
        title="Test Gateway",
        **overrides,
    )


@pytest.fixture
async def gw_with_personal_agent():
    """Create a gateway and patch an agent to have scope=personal."""
    gw = _make_gateway()
    async with gw:
        # Patch one agent to be personal with a setup_schema
        snapshot = gw._snapshot
        if snapshot and snapshot.workspace:
            for agent in snapshot.workspace.agents.values():
                agent.scope = "personal"
                agent.setup_schema = {
                    "type": "object",
                    "required": ["api_key"],
                    "properties": {
                        "api_key": {
                            "type": "string",
                            "description": "API key",
                            "sensitive": True,
                        },
                        "style": {
                            "type": "string",
                            "enum": ["brief", "detailed"],
                            "default": "brief",
                        },
                    },
                }
                break  # only patch the first agent
        yield gw


@pytest.fixture
async def personal_client(gw_with_personal_agent: Gateway) -> AsyncClient:
    transport = ASGITransport(app=gw_with_personal_agent)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


def _get_first_agent_id(gw: Gateway) -> str:
    snapshot = gw._snapshot
    assert snapshot and snapshot.workspace
    return next(iter(snapshot.workspace.agents))


def _mock_request(gw: Gateway) -> MagicMock:
    """Create a mock request with auth context pointing at the gateway."""
    request = MagicMock()
    request.app = gw
    request.scope = {"auth": MagicMock()}
    return request


class TestGetSetupSchema:
    async def test_returns_schema_for_personal_agent(
        self,
        gw_with_personal_agent: Gateway,
        personal_client: AsyncClient,
    ) -> None:
        agent_id = _get_first_agent_id(gw_with_personal_agent)
        resp = await personal_client.get(f"/v1/agents/{agent_id}/setup-schema")
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_id"] == agent_id
        assert body["scope"] == "personal"
        assert body["setup_schema"]["type"] == "object"

    async def test_404_for_unknown_agent(
        self,
        personal_client: AsyncClient,
    ) -> None:
        resp = await personal_client.get("/v1/agents/nonexistent/setup-schema")
        assert resp.status_code == 404

    async def test_400_for_global_agent(self) -> None:
        gw = _make_gateway()
        async with gw:
            transport = ASGITransport(app=gw)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                agent_id = _get_first_agent_id(gw)
                resp = await ac.get(f"/v1/agents/{agent_id}/setup-schema")
                assert resp.status_code == 400
                assert "not a personal agent" in resp.json()["error"]["message"]


class TestSaveUserConfig:
    async def test_save_requires_auth(
        self,
        gw_with_personal_agent: Gateway,
        personal_client: AsyncClient,
    ) -> None:
        agent_id = _get_first_agent_id(gw_with_personal_agent)
        resp = await personal_client.post(
            f"/v1/agents/{agent_id}/config",
            json={"api_key": "secret123"},
        )
        # No auth context → 401
        assert resp.status_code == 401

    async def test_save_config_with_auth(
        self,
        gw_with_personal_agent: Gateway,
    ) -> None:
        """Test saving config when auth context is available."""
        from agent_gateway.api.routes.user_config import save_user_config

        gw = gw_with_personal_agent
        agent_id = _get_first_agent_id(gw)
        request = _mock_request(gw)

        with (
            patch.object(gw, "_derive_user_id", return_value="user-1"),
            patch.dict(os.environ, {"AGENT_GATEWAY_SECRET_KEY": "test-secret-key-1234"}),
        ):
            resp = await save_user_config(
                request=request,
                body={"api_key": "secret123", "style": "brief"},
                agent_id=agent_id,
            )
            assert resp.status_code == 200
            data = json.loads(resp.body)
            assert data["user_id"] == "user-1"
            assert data["agent_id"] == agent_id
            assert data["setup_completed"] is True

    async def test_save_config_not_personal(
        self,
    ) -> None:
        """Test saving config for a global agent returns 400."""
        from agent_gateway.api.routes.user_config import save_user_config

        gw = _make_gateway()
        async with gw:
            agent_id = _get_first_agent_id(gw)
            request = _mock_request(gw)

            with patch.object(gw, "_derive_user_id", return_value="user-1"):
                resp = await save_user_config(
                    request=request,
                    body={"key": "value"},
                    agent_id=agent_id,
                )
                assert resp.status_code == 400

    async def test_save_config_no_auth(
        self,
        gw_with_personal_agent: Gateway,
    ) -> None:
        """Test saving config with no user_id returns 401."""
        from agent_gateway.api.routes.user_config import save_user_config

        gw = gw_with_personal_agent
        agent_id = _get_first_agent_id(gw)
        request = _mock_request(gw)

        with patch.object(gw, "_derive_user_id", return_value=None):
            resp = await save_user_config(
                request=request,
                body={"api_key": "secret123"},
                agent_id=agent_id,
            )
            assert resp.status_code == 401

    async def test_validation_against_schema(
        self,
        gw_with_personal_agent: Gateway,
    ) -> None:
        """Test that setup_schema validation is enforced."""
        from agent_gateway.api.routes.user_config import save_user_config

        gw = gw_with_personal_agent
        agent_id = _get_first_agent_id(gw)
        request = _mock_request(gw)

        with patch.object(gw, "_derive_user_id", return_value="user-1"):
            # Invalid body (missing required field api_key, wrong type for style)
            resp = await save_user_config(
                request=request,
                body={"style": 123},  # api_key missing
                agent_id=agent_id,
            )
            assert resp.status_code == 422


class TestGetUserConfig:
    async def test_get_returns_redacted_secrets(self) -> None:
        """Test that get_user_config returns redacted secrets."""
        from datetime import UTC, datetime

        from agent_gateway.api.routes.user_config import get_user_config
        from agent_gateway.persistence.backends.sqlite import SqliteBackend

        gw = _make_gateway()
        async with gw:
            # Replace with a real backend for the get test
            backend = SqliteBackend(path=":memory:")
            await backend.initialize()
            gw._user_agent_config_repo = backend.user_agent_config_repo

            agent_id = _get_first_agent_id(gw)

            # Store a config first
            now = datetime.now(UTC)
            config = UserAgentConfig(
                user_id="user-1",
                agent_id=agent_id,
                instructions="Custom prompt",
                config_values={"style": "brief"},
                encrypted_secrets={"api_key": "enc_value"},
                setup_completed=True,
                created_at=now,
                updated_at=now,
            )
            await gw._user_agent_config_repo.upsert(config)

            request = _mock_request(gw)
            with patch.object(gw, "_derive_user_id", return_value="user-1"):
                resp = await get_user_config(request=request, agent_id=agent_id)
                assert resp.status_code == 200
                data = json.loads(resp.body)
                assert data["instructions"] == "Custom prompt"
                assert data["secrets"] == {"api_key": "***"}
                assert data["setup_completed"] is True

            await backend.dispose()

    async def test_get_returns_404_when_no_config(
        self,
        gw_with_personal_agent: Gateway,
    ) -> None:
        from agent_gateway.api.routes.user_config import get_user_config

        gw = gw_with_personal_agent
        agent_id = _get_first_agent_id(gw)
        request = _mock_request(gw)

        with patch.object(gw, "_derive_user_id", return_value="user-1"):
            resp = await get_user_config(request=request, agent_id=agent_id)
            assert resp.status_code == 404

    async def test_get_requires_auth(
        self,
        gw_with_personal_agent: Gateway,
    ) -> None:
        from agent_gateway.api.routes.user_config import get_user_config

        gw = gw_with_personal_agent
        agent_id = _get_first_agent_id(gw)
        request = _mock_request(gw)

        with patch.object(gw, "_derive_user_id", return_value=None):
            resp = await get_user_config(request=request, agent_id=agent_id)
            assert resp.status_code == 401


class TestDeleteUserConfig:
    async def test_delete_existing_config(self) -> None:
        from datetime import UTC, datetime

        from agent_gateway.api.routes.user_config import delete_user_config
        from agent_gateway.persistence.backends.sqlite import SqliteBackend

        gw = _make_gateway()
        async with gw:
            backend = SqliteBackend(path=":memory:")
            await backend.initialize()
            gw._user_agent_config_repo = backend.user_agent_config_repo

            agent_id = _get_first_agent_id(gw)

            now = datetime.now(UTC)
            config = UserAgentConfig(
                user_id="user-1",
                agent_id=agent_id,
                created_at=now,
                updated_at=now,
            )
            await gw._user_agent_config_repo.upsert(config)

            request = _mock_request(gw)
            with patch.object(gw, "_derive_user_id", return_value="user-1"):
                resp = await delete_user_config(request=request, agent_id=agent_id)
                assert resp.status_code == 200

            await backend.dispose()

    async def test_delete_nonexistent_config(
        self,
        gw_with_personal_agent: Gateway,
    ) -> None:
        from agent_gateway.api.routes.user_config import delete_user_config

        gw = gw_with_personal_agent
        agent_id = _get_first_agent_id(gw)
        request = _mock_request(gw)

        with patch.object(gw, "_derive_user_id", return_value="user-1"):
            resp = await delete_user_config(request=request, agent_id=agent_id)
            assert resp.status_code == 404

    async def test_delete_requires_auth(
        self,
        gw_with_personal_agent: Gateway,
    ) -> None:
        from agent_gateway.api.routes.user_config import delete_user_config

        gw = gw_with_personal_agent
        request = _mock_request(gw)

        with patch.object(gw, "_derive_user_id", return_value=None):
            resp = await delete_user_config(request=request, agent_id="any-agent")
            assert resp.status_code == 401
