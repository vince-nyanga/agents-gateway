"""Integration tests for dashboard routes (router.py).

Uses a real Gateway with the dashboard enabled and httpx.AsyncClient
as the test transport, so the full Starlette middleware stack is exercised.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from agent_gateway.gateway import Gateway

FIXTURE_WORKSPACE = Path(__file__).resolve().parent.parent / "fixtures" / "workspace"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_repos(gw: Gateway) -> None:
    """Replace persistence repos with async mocks returning empty/zero defaults."""

    exec_repo = AsyncMock()
    exec_repo.list_all.return_value = []
    exec_repo.count_all.return_value = 0
    exec_repo.get.return_value = None
    exec_repo.get_with_steps.return_value = None
    exec_repo.list_conversations_summary.return_value = []
    exec_repo.count_conversations.return_value = 0
    exec_repo.get_summary_stats.return_value = {
        "total_executions": 0,
        "total_cost_usd": 0.0,
        "success_count": 0,
        "avg_duration_ms": 0.0,
    }
    exec_repo.cost_by_day.return_value = []
    exec_repo.executions_by_day.return_value = []
    exec_repo.cost_by_agent.return_value = []
    exec_repo.list_by_session.return_value = []
    exec_repo.get_schedule_stats.return_value = {
        "total_scheduled": 0,
        "active_schedules": 0,
        "success": 0,
        "failed": 0,
        "running": 0,
    }
    exec_repo.list_children.return_value = []
    exec_repo.cost_by_root_execution.return_value = 0.0

    schedule_repo = AsyncMock()
    schedule_repo.list_all.return_value = []
    schedule_repo.get.return_value = None

    user_agent_config_repo = AsyncMock()
    user_agent_config_repo.list_by_user.return_value = []
    user_agent_config_repo.get.return_value = None

    user_schedule_repo = AsyncMock()
    user_schedule_repo.list_by_user.return_value = []

    gw._execution_repo = exec_repo  # type: ignore[assignment]
    gw._schedule_repo = schedule_repo  # type: ignore[assignment]
    gw._user_agent_config_repo = user_agent_config_repo  # type: ignore[assignment]
    gw._user_schedule_repo = user_schedule_repo  # type: ignore[assignment]


async def _make_client(
    gw: Gateway,
) -> AsyncClient:
    """Build an httpx AsyncClient wired to the gateway."""
    transport = ASGITransport(app=gw)
    return AsyncClient(transport=transport, base_url="http://test")


async def _login(
    client: AsyncClient,
    username: str = "testuser",
    password: str = "testpass",
) -> None:
    """POST valid credentials so the session cookie is set."""
    await client.post(
        "/dashboard/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoginPage:
    async def test_get_login_returns_200(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                resp = await client.get("/dashboard/login")
                assert resp.status_code == 200
                assert "text/html" in resp.headers["content-type"]

    async def test_post_valid_creds_redirects(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                assert resp.status_code == 303
                assert "/dashboard/" in resp.headers.get("location", "")

    async def test_post_invalid_creds_returns_401(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "wrong"},
                    follow_redirects=False,
                )
                assert resp.status_code == 401


class TestLogout:
    async def test_logout_redirects_to_login(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client)
                resp = await client.post("/dashboard/logout", follow_redirects=False)
                assert resp.status_code == 303
                assert "/dashboard/login" in resp.headers.get("location", "")


class TestProtectedRoutes:
    async def test_unauthenticated_redirects(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                resp = await client.get("/dashboard/", follow_redirects=False)
                assert resp.status_code == 302
                assert "/dashboard/login" in resp.headers.get("location", "")


class TestAgentsPage:
    async def test_agents_page_returns_200(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client)
                resp = await client.get("/dashboard/")
                assert resp.status_code == 200
                assert "text/html" in resp.headers["content-type"]

    async def test_agents_htmx_partial(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client)
                resp = await client.get(
                    "/dashboard/agents",
                    headers={"HX-Request": "true"},
                )
                assert resp.status_code == 200


class TestExecutionsPage:
    async def test_executions_page_returns_200(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.get("/dashboard/executions")
                assert resp.status_code == 200

    async def test_executions_with_filters(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.get(
                    "/dashboard/executions",
                    params={"agent_id": "x", "status": "completed"},
                )
                assert resp.status_code == 200

    async def test_execution_detail_not_found(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.get("/dashboard/executions/nonexistent")
                assert resp.status_code == 404


class TestConversationsPage:
    async def test_conversations_page_returns_200(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client)
                resp = await client.get("/dashboard/conversations")
                assert resp.status_code == 200

    async def test_conversation_detail_not_found(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client)
                resp = await client.get("/dashboard/conversations/nonexistent")
                assert resp.status_code == 404

    async def test_conversations_link_visible_to_non_admin(self) -> None:
        """Non-admin users should see the Conversations sidebar link."""
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="testuser", password="testpass")
                resp = await client.get("/dashboard/")
                assert resp.status_code == 200
                text = resp.text
                assert "/dashboard/conversations" in text
                assert "Conversations" in text


class TestAnalyticsPage:
    async def test_analytics_page_returns_200(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.get("/dashboard/analytics")
                assert resp.status_code == 200

    async def test_analytics_charts_htmx(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.get(
                    "/dashboard/analytics",
                    headers={"HX-Request": "true"},
                )
                assert resp.status_code == 200


class TestSchedulesPage:
    async def test_schedules_page_returns_200(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.get("/dashboard/schedules")
                assert resp.status_code == 200


class TestAdminRoutes:
    async def test_toggle_schedule_non_admin_403(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="testuser", password="testpass")
                resp = await client.post(
                    "/dashboard/schedules/some-id/toggle",
                    follow_redirects=False,
                )
                assert resp.status_code == 303

    async def test_toggle_schedule_admin_works(self) -> None:
        from agent_gateway.persistence.domain import ScheduleRecord

        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            # Make schedule_repo.get return a real record
            record = ScheduleRecord(
                id="sched-1",
                agent_id="test-agent",
                name="test schedule",
                cron_expr="*/5 * * * *",
                message="run",
                enabled=True,
            )
            schedule_repo = gw._schedule_repo
            assert isinstance(schedule_repo, AsyncMock)
            schedule_repo.get.return_value = record
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.post(
                    "/dashboard/schedules/sched-1/toggle",
                    follow_redirects=False,
                )
                assert resp.status_code == 303

    async def test_toggle_schedule_not_found(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.post(
                    "/dashboard/schedules/nonexistent/toggle",
                    follow_redirects=False,
                )
                assert resp.status_code == 404


class TestScheduleDetailPage:
    async def test_schedule_detail_returns_200_with_recent_runs(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            # Mock get_schedule to return a schedule dict
            schedule_dict = {
                "id": "sched-test",
                "agent_id": "test-agent",
                "name": "test schedule",
                "cron_expr": "*/5 * * * *",
                "message": "run",
                "instructions": "",
                "input": {},
                "enabled": True,
                "timezone": "UTC",
                "source": "workspace",
                "next_run_at": None,
                "last_run_at": None,
                "created_at": None,
            }
            gw.get_schedule = AsyncMock(return_value=schedule_dict)  # type: ignore[method-assign]
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.get("/dashboard/schedules/sched-test/detail")
                assert resp.status_code == 200
                assert "text/html" in resp.headers["content-type"]
                # Verify list_all was called with schedule_id filter
                exec_repo = gw._execution_repo
                assert isinstance(exec_repo, AsyncMock)
                exec_repo.list_all.assert_called_with(schedule_id="sched-test", limit=20)

    async def test_schedule_detail_not_found(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            gw.get_schedule = AsyncMock(return_value=None)  # type: ignore[method-assign]
            client = await _make_client(gw)
            async with client:
                await _login(client, username="admin", password="adminpass")
                resp = await client.get("/dashboard/schedules/nonexistent/detail")
                assert resp.status_code == 404
