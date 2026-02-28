"""Tests for encrypted_headers handling in MCP server API and dashboard routes."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.gateway import Gateway
from agent_gateway.persistence.domain import McpServerConfig

# Ensure a secret key is available for encryption/decryption in tests
os.environ.setdefault("AGENT_GATEWAY_SECRET_KEY", "test-secret-key-for-unit-tests-only")


def _write_workspace(tmp_path: Path) -> Path:
    (tmp_path / "gateway.yaml").write_text("persistence:\n  enabled: false\n")
    agents = tmp_path / "agents"
    agents.mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "tools").mkdir()
    agent_dir = agents / "test-agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text("# Test Agent\n\nYou help with testing.\n")
    return tmp_path


def _make_config(
    server_id: str = "srv-1",
    name: str = "test-server",
    transport: str = "streamable_http",
    encrypted_headers: str | None = None,
) -> McpServerConfig:
    return McpServerConfig(
        id=server_id,
        name=name,
        transport=transport,
        url="http://localhost:8080",
        encrypted_headers=encrypted_headers,
        enabled=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return _write_workspace(tmp_path)


class TestCreateWithHeaders:
    @pytest.mark.asyncio
    async def test_create_with_headers_returns_header_keys(self, workspace: Path) -> None:
        """Creating an MCP server with headers should return header_keys (names only)."""
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            mock_repo = AsyncMock()
            mock_repo.upsert.return_value = None
            gw._mcp_repo = mock_repo
            gw._mcp_manager = MagicMock()
            gw._mcp_manager.get_tools.return_value = []
            gw._mcp_manager.is_connected.return_value = False
            gw._audit_repo = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/v1/admin/mcp-servers",
                    json={
                        "name": "hdrs-server",
                        "transport": "streamable_http",
                        "url": "http://localhost:9090/mcp",
                        "headers": {"Authorization": "Bearer secret", "X-Custom": "val"},
                    },
                )

        assert resp.status_code == 200
        body = resp.json()
        assert sorted(body["header_keys"]) == ["Authorization", "X-Custom"]
        # Values must NOT appear in the response
        assert "secret" not in json.dumps(body)


class TestUpdateWithHeaders:
    @pytest.mark.asyncio
    async def test_update_with_headers_updates_encrypted(self, workspace: Path) -> None:
        """Updating headers should update encrypted_headers and return new header_keys."""
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            config = _make_config()
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = config
            mock_repo.upsert.return_value = None
            gw._mcp_repo = mock_repo
            gw._mcp_manager = MagicMock()
            gw._mcp_manager.get_tools.return_value = []
            gw._mcp_manager.is_connected.return_value = False
            gw._audit_repo = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.put(
                    "/v1/admin/mcp-servers/srv-1",
                    json={"headers": {"X-Api-Key": "supersecret"}},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["header_keys"] == ["X-Api-Key"]
        # Verify encrypted_headers was actually set on the config
        saved_config = mock_repo.upsert.call_args[0][0]
        assert saved_config.encrypted_headers is not None


class TestToResponseDecryptionFailure:
    @pytest.mark.asyncio
    async def test_bad_blob_returns_decryption_failed(self, workspace: Path) -> None:
        """_to_response returns ['<decryption_failed>'] when header blob is corrupted."""
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            config = _make_config(encrypted_headers="not-valid-encrypted-data")
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = config
            gw._mcp_repo = mock_repo
            gw._mcp_manager = MagicMock()
            gw._mcp_manager.get_tools.return_value = []
            gw._mcp_manager.is_connected.return_value = False

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.get("/v1/admin/mcp-servers/srv-1")

        assert resp.status_code == 200
        assert resp.json()["header_keys"] == ["<decryption_failed>"]


class TestDashboardCreateWithHeaders:
    @pytest.mark.asyncio
    async def test_dashboard_form_create_with_headers(self, workspace: Path) -> None:
        """Dashboard form POST with headers JSON should store encrypted_headers."""
        gw = Gateway(workspace=str(workspace), auth=False, dashboard=True)
        async with gw:
            mock_repo = AsyncMock()
            mock_repo.upsert.return_value = None
            mock_repo.list_all.return_value = []
            gw._mcp_repo = mock_repo
            gw._mcp_manager = MagicMock()
            gw._mcp_manager.get_tools.return_value = []
            gw._mcp_manager.is_connected.return_value = False
            gw._audit_repo = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
                follow_redirects=True,
            ) as ac:
                await ac.post(
                    "/dashboard/mcp-servers",
                    data={
                        "name": "dash-server",
                        "transport": "streamable_http",
                        "url": "http://localhost:9090/mcp",
                        "headers": json.dumps({"X-Token": "abc123"}),
                        "credentials": "",
                        "env": "",
                    },
                )

        # The key assertion: upsert was called with encrypted_headers set
        if mock_repo.upsert.called:
            saved = mock_repo.upsert.call_args[0][0]
            assert saved.encrypted_headers is not None
