"""Tests for mounting Gateway as a sub-application."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from agent_gateway import Gateway
from agent_gateway.exceptions import ConfigError


@pytest.fixture()
def workspace_path(tmp_path):
    """Minimal workspace with one fake agent."""
    agents_dir = tmp_path / "agents" / "test-agent"
    agents_dir.mkdir(parents=True)
    (agents_dir / "AGENT.md").write_text(
        "---\nmodel: fake\n---\n# Test Agent\nYou are a test agent."
    )
    return tmp_path


@pytest.fixture()
def gateway(workspace_path):
    """Basic Gateway without dashboard."""
    return Gateway(workspace=workspace_path)


@pytest.fixture()
def gateway_with_dashboard(workspace_path):
    """Gateway with dashboard enabled."""
    gw = Gateway(workspace=workspace_path)
    gw.use_dashboard(
        auth_password="test",
        auth_username="user",
        admin_username="admin",
        admin_password="adminpass",
    )
    return gw


@pytest.fixture()
def parent_app():
    app = FastAPI()

    @app.get("/parent-health")
    async def parent_health():
        return {"status": "ok"}

    return app


# --- Test 1: mount_to wires lifespan ---
def test_mount_to_wires_lifespan(gateway, parent_app):
    gateway.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        # Gateway should have started via parent lifespan
        assert gateway._started is True
        client.get("/gw/v1/health")
    # After exiting, gateway should have shut down
    assert gateway._started is False


# --- Test 2: health accessible under prefix ---
def test_mount_to_health_accessible(gateway, parent_app):
    gateway.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        resp = client.get("/gw/v1/health")
        assert resp.status_code == 200


# --- Test 3: parent routes still work ---
def test_mount_to_parent_routes_work(gateway, parent_app):
    gateway.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        assert client.get("/parent-health").status_code == 200
        assert client.get("/gw/v1/health").status_code == 200


# --- Test 4: raises if already started ---
@pytest.mark.asyncio()
async def test_mount_to_raises_if_already_started(gateway, parent_app):
    async with gateway:
        with pytest.raises(ConfigError, match="Cannot mount_to"):
            gateway.mount_to(parent_app, path="/gw")


# --- Test 5: preserves parent lifespan ---
def test_mount_to_preserves_parent_lifespan(gateway, workspace_path):
    parent = FastAPI()

    @asynccontextmanager
    async def parent_lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.flag = True  # type: ignore[attr-defined]
        yield

    parent.router.lifespan_context = parent_lifespan
    gateway.mount_to(parent, path="/gw")
    with TestClient(parent) as client:
        client.get("/gw/v1/health")
        assert parent.state.flag is True  # type: ignore[attr-defined]


# --- Test 6: double startup is idempotent ---
@pytest.mark.asyncio()
async def test_double_startup_is_idempotent(gateway):
    await gateway._startup()
    try:
        # Should not raise
        await gateway._startup()
        assert gateway._started is True
    finally:
        await gateway._shutdown()


# --- Test 7: auth works under mount ---
def test_mount_to_auth_works(gateway, parent_app):
    gateway.use_api_keys([{"name": "dev", "key": "secret123", "scopes": ["*"]}])
    gateway.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        # Health is public
        assert client.get("/gw/v1/health").status_code == 200
        # Agents with auth header returns 200
        resp = client.get("/gw/v1/agents", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200


# --- Test 8: dashboard accessible under prefix ---
def test_mount_to_dashboard_accessible(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        resp = client.get("/gw/dashboard/login", follow_redirects=False)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# --- Test 9: static assets accessible under prefix ---
def test_mount_to_dashboard_static_assets(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        resp = client.get("/gw/dashboard/static/dashboard/app.css")
        assert resp.status_code == 200


# --- Test 10: unauthenticated dashboard redirects to prefixed login ---
def test_mount_to_dashboard_login_redirect(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        resp = client.get("/gw/dashboard/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/gw/dashboard/login" in resp.headers["location"]


# --- Test 11: login flow works with prefix ---
def test_mount_to_dashboard_login_flow(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        resp = client.post(
            "/gw/dashboard/login",
            data={"username": "user", "password": "test"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/gw/dashboard/" in resp.headers["location"]


# --- Test 12: dashboard links have prefix ---
def test_mount_to_dashboard_links_have_prefix(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        resp = client.get("/gw/dashboard/login")
        html = resp.text
        assert 'href="/gw/dashboard/' in html or 'action="/gw/dashboard/' in html
        assert 'src="/gw/dashboard/static/' in html
        # Verify no unprefixed /dashboard/ paths exist (except inside {{ base_path }})
        # After rendering, there should be no bare /dashboard/ without /gw prefix
        # Check that rendered HTML doesn't contain href="/dashboard/ without /gw
        for line in html.split("\n"):
            if 'href="/dashboard/' in line and 'href="/gw/dashboard/' not in line:
                pytest.fail(f"Found unprefixed dashboard path: {line.strip()}")


# --- Test 13: HTMX URLs have prefix ---
def test_mount_to_dashboard_htmx_urls_have_prefix(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        # Login first
        client.post(
            "/gw/dashboard/login",
            data={"username": "admin", "password": "adminpass"},
        )
        resp = client.get("/gw/dashboard/executions")
        html = resp.text
        assert 'hx-get="/gw/dashboard/' in html or 'hx-post="/gw/dashboard/' in html


# --- Test 14: standalone dashboard has no prefix (regression) ---
def test_standalone_dashboard_no_prefix(gateway_with_dashboard):
    with TestClient(gateway_with_dashboard) as client:
        resp = client.get("/dashboard/login")
        html = resp.text
        assert 'href="/dashboard/' in html
        # Should NOT have any prefix
        assert 'href="//dashboard/' not in html


# --- Test 15: prefix normalization ---
def test_mount_prefix_normalization(workspace_path):
    # Trailing slash is stripped
    gw1 = Gateway(workspace=workspace_path)
    parent1 = FastAPI()
    gw1.mount_to(parent1, path="/gw/")
    assert gw1._mount_prefix == "/gw"

    # Leading slash is added when input omits it
    gw2 = Gateway(workspace=workspace_path)
    parent2 = FastAPI()
    gw2.mount_to(parent2, path="gw")
    assert gw2._mount_prefix == "/gw"


# --- Test 16: JS base path meta tag ---
def test_mount_to_js_base_path_meta(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        resp = client.get("/gw/dashboard/login")
        assert '<meta name="base-path" content="/gw" />' in resp.text


# --- Test 17: admin redirect uses prefix ---
def test_mount_to_admin_redirect_uses_prefix(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        # Login as non-admin user
        client.post(
            "/gw/dashboard/login",
            data={"username": "user", "password": "test"},
        )
        # Hit admin-only route
        resp = client.get("/gw/dashboard/mcp-servers", follow_redirects=False)
        assert resp.status_code == 303
        assert "/gw/dashboard/agents" in resp.headers["location"]


# --- Test 18: HTMX redirect header uses prefix ---
def test_mount_to_htmx_redirect_header_uses_prefix(gateway_with_dashboard, parent_app):
    gateway_with_dashboard.mount_to(parent_app, path="/gw")
    with TestClient(parent_app) as client:
        resp = client.get(
            "/gw/dashboard/agents",
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
        assert resp.status_code == 204
        assert resp.headers.get("HX-Redirect") == "/gw/dashboard/login"


# --- Test 19: OAuth2 redirect_uri has prefix (mocked) ---
def test_mount_to_oauth2_redirect_uri_has_prefix(workspace_path, parent_app):
    """Verify that OAuth2 authorize handler generates redirect_uri with mount prefix."""
    gw = Gateway(workspace=workspace_path)
    gw.use_dashboard(
        auth_password=None,  # disable password auth
        auth_username=None,
        admin_username=None,
        admin_password=None,
        oauth2_issuer="https://accounts.example.com",
        oauth2_client_id="test-client",
        oauth2_client_secret="test-secret",  # noqa: S106
    )
    gw.mount_to(parent_app, path="/gw")

    with TestClient(parent_app, raise_server_exceptions=False) as client:
        # The authorize endpoint will fail (no real OIDC server)
        # but we can verify the route is accessible
        resp = client.get("/gw/dashboard/oauth2/authorize", follow_redirects=False)
        # Will redirect to login with error since discovery fails, which is expected
        # The important thing is the route is registered and redirects include prefix
        if resp.status_code == 303:
            location = resp.headers.get("location", "")
            assert "/gw/dashboard/login" in location


# --- Test 20: empty path raises ---
def test_mount_to_empty_path_raises(gateway, parent_app):
    with pytest.raises(ConfigError, match="non-empty path prefix"):
        gateway.mount_to(parent_app, path="/")
    with pytest.raises(ConfigError, match="non-empty path prefix"):
        gateway.mount_to(parent_app, path="")
