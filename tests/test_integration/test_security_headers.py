"""Tests for security headers middleware integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.config import SecurityConfig
from agent_gateway.gateway import Gateway

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURE_WORKSPACE = FIXTURES_DIR / "workspace"


def _make_gateway(**overrides: object) -> Gateway:
    gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
    if overrides:
        gw.use_security_headers(**overrides)  # type: ignore[arg-type]
    return gw


@pytest.fixture
async def client() -> AsyncClient:
    """Client with default security headers (enabled by default)."""
    gw = _make_gateway()
    async with gw:
        transport = ASGITransport(app=gw)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac  # type: ignore[misc]


class TestSecurityHeadersDefault:
    async def test_all_default_headers_present(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
        assert resp.headers["content-security-policy"] == "default-src 'self'"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


class TestSecurityHeadersCustom:
    async def test_custom_x_frame_options(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        gw.use_security_headers(x_frame_options="SAMEORIGIN")
        async with gw:
            transport = ASGITransport(app=gw)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/health")
                assert resp.headers["x-frame-options"] == "SAMEORIGIN"
                # Other headers remain at defaults
                assert resp.headers["x-content-type-options"] == "nosniff"


class TestSecurityHeadersDisabled:
    async def test_no_security_headers_when_disabled(self) -> None:
        gw = _make_gateway(enabled=False)
        async with gw:
            transport = ASGITransport(app=gw)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/health")
                assert "x-content-type-options" not in resp.headers
                assert "x-frame-options" not in resp.headers
                assert "strict-transport-security" not in resp.headers
                assert "referrer-policy" not in resp.headers


class TestSecurityHeadersDashboardCsp:
    async def test_dashboard_gets_relaxed_csp(self) -> None:
        """Test the middleware directly to verify dashboard CSP logic."""
        from agent_gateway.api.middleware.security import SecurityHeadersMiddleware

        config = SecurityConfig()
        captured_headers: list[tuple[bytes, bytes]] = []

        async def mock_app(
            scope: dict,
            receive: object,
            send: object,  # noqa: ARG001
        ) -> None:
            # Simulate sending a response
            assert callable(send)
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def capture_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                captured_headers.extend(message.get("headers", []))

        mw = SecurityHeadersMiddleware(app=mock_app, config=config)

        # Test API path
        captured_headers.clear()
        await mw(
            {"type": "http", "path": "/v1/health"},
            lambda: None,  # type: ignore[arg-type,return-value]
            capture_send,
        )
        csp_values = [v.decode() for k, v in captured_headers if k == b"content-security-policy"]
        assert csp_values == ["default-src 'self'"]

        # Test dashboard path
        captured_headers.clear()
        await mw(
            {"type": "http", "path": "/dashboard/index"},
            lambda: None,  # type: ignore[arg-type,return-value]
            capture_send,
        )
        csp_values = [v.decode() for k, v in captured_headers if k == b"content-security-policy"]
        assert len(csp_values) == 1
        assert "'unsafe-inline'" in csp_values[0]


class TestUseSecurityHeadersApi:
    def test_returns_self(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        result = gw.use_security_headers()
        assert result is gw

    async def test_after_start_raises(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        async with gw:
            with pytest.raises(RuntimeError, match="Cannot configure security headers"):
                gw.use_security_headers()

    def test_config_stored_correctly(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        gw.use_security_headers(
            x_frame_options="SAMEORIGIN",
            content_security_policy="default-src 'none'",
        )
        assert gw._pending_security_config is not None
        assert gw._pending_security_config.enabled is True
        assert gw._pending_security_config.x_frame_options == "SAMEORIGIN"
        assert gw._pending_security_config.content_security_policy == "default-src 'none'"
        # Defaults preserved for unspecified fields
        assert gw._pending_security_config.x_content_type_options == "nosniff"

    def test_dashboard_csp_override(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        gw.use_security_headers(dashboard_content_security_policy="default-src 'self'")
        assert gw._pending_security_config is not None
        assert (
            gw._pending_security_config.dashboard_content_security_policy == "default-src 'self'"
        )


class TestSecurityHeadersOnErrorResponses:
    async def test_headers_on_404(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/nonexistent-endpoint")
        assert resp.status_code in (404, 405)
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
