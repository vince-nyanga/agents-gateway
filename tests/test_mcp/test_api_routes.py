"""Tests for MCP server CRUD API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.exceptions import McpAuthError, McpConnectionError
from agent_gateway.gateway import Gateway
from agent_gateway.persistence.domain import McpServerConfig


def _write_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with persistence disabled."""
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
    transport: str = "stdio",
) -> McpServerConfig:
    return McpServerConfig(
        id=server_id,
        name=name,
        transport=transport,
        command="echo" if transport == "stdio" else None,
        url="http://localhost:8080" if transport == "streamable_http" else None,
        enabled=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return _write_workspace(tmp_path)


class TestMcpServerRoutes:
    @pytest.mark.asyncio
    async def test_list_mcp_servers(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            mock_repo = AsyncMock()
            mock_repo.list_all.return_value = [_make_config()]
            gw._mcp_repo = mock_repo
            gw._mcp_manager = MagicMock()
            gw._mcp_manager.get_tools.return_value = []
            gw._mcp_manager.is_connected.return_value = True

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.get("/v1/admin/mcp-servers")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["name"] == "test-server"
        assert body[0]["connected"] is True

    @pytest.mark.asyncio
    async def test_get_mcp_server_not_found(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = None
            gw._mcp_repo = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.get("/v1/admin/mcp-servers/nonexistent")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_mcp_server_found(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            config = _make_config()
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
        assert resp.json()["name"] == "test-server"

    @pytest.mark.asyncio
    async def test_create_mcp_server(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            mock_repo = AsyncMock()
            mock_repo.upsert.return_value = None
            gw._mcp_repo = mock_repo
            gw._mcp_manager = MagicMock()
            gw._mcp_manager.get_tools.return_value = []
            gw._mcp_manager.is_connected.return_value = False

            mock_audit = AsyncMock()
            gw._audit_repo = mock_audit

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/v1/admin/mcp-servers",
                    json={
                        "name": "new-server",
                        "transport": "stdio",
                        "command": "python",
                        "args": ["-m", "server"],
                    },
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "new-server"
        assert body["transport"] == "stdio"
        mock_repo.upsert.assert_called_once()
        mock_audit.log.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_mcp_server_invalid_transport_combo(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with (
            gw,
            AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac,
        ):
            # stdio with url should fail validation
            resp = await ac.post(
                "/v1/admin/mcp-servers",
                json={
                    "name": "bad",
                    "transport": "stdio",
                    "url": "http://example.com",
                },
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_mcp_server(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            config = _make_config()
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = config
            mock_repo.delete.return_value = True
            gw._mcp_repo = mock_repo
            mock_manager = AsyncMock()
            gw._mcp_manager = mock_manager

            mock_audit = AsyncMock()
            gw._audit_repo = mock_audit

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.delete("/v1/admin/mcp-servers/srv-1")

            assert resp.status_code == 200
            assert resp.json()["deleted"] is True
            mock_manager.disconnect_one.assert_called_once_with("test-server")

    @pytest.mark.asyncio
    async def test_delete_mcp_server_not_found(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = None
            gw._mcp_repo = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.delete("/v1/admin/mcp-servers/nonexistent")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_test_mcp_server_success(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            config = _make_config()
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = config
            gw._mcp_repo = mock_repo
            mock_manager = AsyncMock()
            mock_manager.test_connection.return_value = {
                "success": True,
                "tool_count": 2,
                "tools": [
                    {"name": "t1", "description": "Tool 1"},
                    {"name": "t2", "description": "Tool 2"},
                ],
            }
            gw._mcp_manager = mock_manager

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.post("/v1/admin/mcp-servers/srv-1/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["tool_count"] == 2
        assert len(body["tools"]) == 2

    @pytest.mark.asyncio
    async def test_test_mcp_server_failure(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            config = _make_config()
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = config
            gw._mcp_repo = mock_repo
            mock_manager = AsyncMock()
            mock_manager.test_connection.side_effect = Exception("Connection refused")
            gw._mcp_manager = mock_manager

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.post("/v1/admin/mcp-servers/srv-1/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "Connection refused"
        assert body["error_code"] == "connection_error"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("exc", "expected_code"),
        [
            pytest.param(
                McpAuthError("bad token", server_name="s"),
                "auth_error",
                id="auth_error",
            ),
            pytest.param(
                McpConnectionError("connection timed out after 10s", server_name="s"),
                "timeout",
                id="timeout",
            ),
            pytest.param(
                ValueError("stdio transport requires 'command'"),
                "config_error",
                id="config_error",
            ),
            pytest.param(
                RuntimeError("something broke"),
                "connection_error",
                id="generic_connection_error",
            ),
        ],
    )
    async def test_test_mcp_server_error_codes(
        self, workspace: Path, exc: Exception, expected_code: str
    ) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            config = _make_config()
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = config
            gw._mcp_repo = mock_repo
            mock_manager = AsyncMock()
            mock_manager.test_connection.side_effect = exc
            gw._mcp_manager = mock_manager

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.post("/v1/admin/mcp-servers/srv-1/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == expected_code

    @pytest.mark.asyncio
    async def test_test_mcp_server_not_found(self, workspace: Path) -> None:
        gw = Gateway(workspace=str(workspace), auth=False)
        async with gw:
            mock_repo = AsyncMock()
            mock_repo.get_by_id.return_value = None
            gw._mcp_repo = mock_repo

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.post("/v1/admin/mcp-servers/nonexistent/test")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_mcp_server(self, workspace: Path) -> None:
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

            mock_audit = AsyncMock()
            gw._audit_repo = mock_audit

            async with AsyncClient(
                transport=ASGITransport(app=gw),
                base_url="http://test",
            ) as ac:
                resp = await ac.put(
                    "/v1/admin/mcp-servers/srv-1",
                    json={"enabled": False},
                )

        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
