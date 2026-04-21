"""Regression tests for the HTTPS-proxy / mounted-gateway fix.

Covers the fixes introduced in
``docs/plans/2026-04-20-fix-mounted-gateway-production-redirects-and-chat-plan.md``:

- F1 session cookie flags (Secure auto-enables under ``trust_forwarded``).
- F2 ``ProxyHeadersMiddleware`` install + middleware ordering.
- F3 OAuth2 ``redirect_uri`` forwarded-header rewrite, GATED by
  ``trust_forwarded`` (untrusted forwarded headers must be ignored).
- F6 SSE response headers (no ``Connection: keep-alive``, ``no-transform``).
- Hot-reload: proxy config persists across ``gw.reload()``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from agent_gateway.dashboard.oauth2 import _build_callback_url
from agent_gateway.gateway import Gateway

FIXTURE_WORKSPACE = Path(__file__).resolve().parent.parent / "fixtures" / "workspace"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_repos(gw: Gateway) -> None:
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


async def _client(gw: Gateway) -> AsyncClient:
    transport = ASGITransport(app=gw)
    return AsyncClient(transport=transport, base_url="http://test")


def _make_dashboard_gateway(
    *,
    trust_forwarded: bool = False,
    session_cookie_https_only: bool | None = None,
    session_cookie_name: str = "agw_dashboard_session",
    session_cookie_domain: str | None = None,
    forwarded_allow_ips: str = "*",
) -> Gateway:
    gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
    if trust_forwarded:
        gw.use_proxy_headers(forwarded_allow_ips=forwarded_allow_ips)
    gw.use_dashboard(
        auth_password="testpass",
        auth_username="testuser",
        admin_username="admin",
        admin_password="adminpass",
        session_cookie_https_only=session_cookie_https_only,
        session_cookie_name=session_cookie_name,
        session_cookie_domain=session_cookie_domain,
    )
    return gw


# ---------------------------------------------------------------------------
# F1 — session cookie Secure flag
# ---------------------------------------------------------------------------


class TestSessionCookieFlags:
    async def test_secure_set_when_trust_forwarded(self) -> None:
        """Auto mode: Secure flag on when proxy trust is enabled."""
        gw = _make_dashboard_gateway(trust_forwarded=True)
        async with gw:
            _mock_repos(gw)
            client = await _client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                set_cookie = resp.headers.get("set-cookie", "")
                assert "secure" in set_cookie.lower()
                assert "agw_dashboard_session" in set_cookie

    async def test_no_secure_when_trust_forwarded_false(self) -> None:
        """Auto mode: Secure OFF for local dev default (no proxy trust)."""
        gw = _make_dashboard_gateway(trust_forwarded=False)
        async with gw:
            _mock_repos(gw)
            client = await _client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                set_cookie = resp.headers.get("set-cookie", "")
                assert "secure" not in set_cookie.lower()

    async def test_explicit_https_only_true(self) -> None:
        """Explicit override beats auto-resolution."""
        gw = _make_dashboard_gateway(
            trust_forwarded=False,
            session_cookie_https_only=True,
        )
        async with gw:
            _mock_repos(gw)
            client = await _client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                assert "secure" in resp.headers.get("set-cookie", "").lower()

    async def test_explicit_https_only_false(self) -> None:
        gw = _make_dashboard_gateway(
            trust_forwarded=True,
            session_cookie_https_only=False,
        )
        async with gw:
            _mock_repos(gw)
            client = await _client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                assert "secure" not in resp.headers.get("set-cookie", "").lower()

    async def test_custom_cookie_name(self) -> None:
        gw = _make_dashboard_gateway(session_cookie_name="myapp_session")
        async with gw:
            _mock_repos(gw)
            client = await _client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                set_cookie = resp.headers.get("set-cookie", "")
                assert "myapp_session=" in set_cookie
                assert "agw_dashboard_session=" not in set_cookie

    async def test_custom_cookie_domain(self) -> None:
        gw = _make_dashboard_gateway(session_cookie_domain="example.com")
        async with gw:
            _mock_repos(gw)
            client = await _client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                set_cookie = resp.headers.get("set-cookie", "").lower()
                assert "domain=example.com" in set_cookie


# ---------------------------------------------------------------------------
# F2 — ordering: trust_forwarded applied BEFORE _maybe_init_dashboard
# ---------------------------------------------------------------------------


class TestStartupOrdering:
    async def test_proxy_config_applied_before_dashboard_init(self) -> None:
        """Ordering regression: the pending ProxyConfig must land on
        ``self._config.proxy`` BEFORE SessionMiddleware is constructed, so the
        auto-resolution of ``https_only`` observes ``trust_forwarded=True``.
        If _maybe_init_dashboard ran first, the cookie would lack Secure."""
        gw = _make_dashboard_gateway(trust_forwarded=True)
        async with gw:
            _mock_repos(gw)
            # Post-startup, both config and middleware reflect the pending val.
            assert gw._config is not None
            assert gw._config.proxy.trust_forwarded is True
            client = await _client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                assert "secure" in resp.headers.get("set-cookie", "").lower()


# ---------------------------------------------------------------------------
# F2 — middleware ordering (ProxyHeaders wraps OUTSIDE Session)
# ---------------------------------------------------------------------------


class TestProxyHeadersEffect:
    """Integration tests: verify ProxyHeadersMiddleware actually rewrites
    ``scope['scheme']`` when trust_forwarded is on. Uses a tiny probe route
    to surface the scheme the request handler sees."""

    async def test_x_forwarded_proto_rewrites_scheme(self) -> None:
        from tests.test_dashboard._scheme_probe import make_scheme_probe_router

        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        gw.use_proxy_headers(forwarded_allow_ips="*")
        gw.include_router(make_scheme_probe_router())

        async with gw:
            client = await _client(gw)
            async with client:
                resp = await client.get(
                    "/_probe/scheme",
                    headers={"X-Forwarded-Proto": "https"},
                )
                assert resp.status_code == 200, resp.text
                assert resp.json()["scheme"] == "https"

    async def test_x_forwarded_proto_ignored_without_flag(self) -> None:
        from tests.test_dashboard._scheme_probe import make_scheme_probe_router

        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        gw.include_router(make_scheme_probe_router())

        async with gw:
            client = await _client(gw)
            async with client:
                resp = await client.get(
                    "/_probe/scheme",
                    headers={"X-Forwarded-Proto": "https"},
                )
                assert resp.status_code == 200, resp.text
                # Without use_proxy_headers() the forwarded header is ignored.
                assert resp.json()["scheme"] == "http"


class TestMiddlewareOrdering:
    async def test_proxy_headers_wraps_outside_session(self) -> None:
        """After startup, walking the built middleware_stack must reach
        ``ProxyHeadersMiddleware`` BEFORE ``SessionMiddleware`` (outer →
        inner). If inverted, session cookie evaluation would see the wrong
        scope['scheme'] on HTTPS proxies."""
        from starlette.middleware.sessions import SessionMiddleware
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        gw = _make_dashboard_gateway(trust_forwarded=True)
        async with gw:
            _mock_repos(gw)
            # Make a request so Starlette finishes building middleware_stack.
            client = await _client(gw)
            async with client:
                await client.get("/dashboard/login", follow_redirects=False)

            stack = gw.middleware_stack
            # Walk outer → inner; record the order we encounter proxy/session.
            proxy_depth: int | None = None
            session_depth: int | None = None
            node: object = stack
            depth = 0
            while node is not None and depth < 50:
                if isinstance(node, ProxyHeadersMiddleware) and proxy_depth is None:
                    proxy_depth = depth
                if isinstance(node, SessionMiddleware) and session_depth is None:
                    session_depth = depth
                inner = getattr(node, "app", None)
                if inner is None or inner is node:
                    break
                node = inner
                depth += 1

            assert proxy_depth is not None, "ProxyHeadersMiddleware missing from stack"
            assert session_depth is not None, "SessionMiddleware missing from stack"
            # Outer runs first per request → smaller depth.
            assert proxy_depth < session_depth, (
                f"ProxyHeaders must wrap OUTSIDE Session: "
                f"proxy_depth={proxy_depth} session_depth={session_depth}"
            )

    async def test_proxy_headers_not_installed_without_flag(self) -> None:
        """Without use_proxy_headers(), ProxyHeadersMiddleware must NOT be
        installed (avoid silently trusting upstream headers)."""
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        gw = _make_dashboard_gateway(trust_forwarded=False)
        async with gw:
            _mock_repos(gw)
            client = await _client(gw)
            async with client:
                await client.get("/dashboard/login", follow_redirects=False)
            node: object = gw.middleware_stack
            for _ in range(50):
                if node is None:
                    break
                assert not isinstance(node, ProxyHeadersMiddleware)
                inner = getattr(node, "app", None)
                if inner is None or inner is node:
                    break
                node = inner


# ---------------------------------------------------------------------------
# F3 — OAuth2 _build_callback_url (with trust_forwarded gate)
# ---------------------------------------------------------------------------


class TestBuildCallbackUrl:
    """Unit tests for the oauth2 helper. The gate is the primary concern: an
    attacker who can reach the app directly (bypassing the proxy) must not be
    able to inject X-Forwarded-Host and hijack the callback URL."""

    def _fake_request(
        self,
        *,
        url: str = "http://internal.local:8000/gw/dashboard/oauth2/callback",
        forwarded_proto: str | None = None,
        forwarded_host: str | None = None,
    ) -> object:
        """Minimal Request stand-in with just the attributes _build_callback_url touches."""

        class _Headers:
            def __init__(self, data: dict[str, str]) -> None:
                self._data = data

            def get(self, key: str, default: str = "") -> str:
                return self._data.get(key.lower(), default)

        hdrs: dict[str, str] = {}
        if forwarded_proto is not None:
            hdrs["x-forwarded-proto"] = forwarded_proto
        if forwarded_host is not None:
            hdrs["x-forwarded-host"] = forwarded_host

        class _Req:
            def __init__(self, url_str: str, headers: dict[str, str]) -> None:
                self._url = url_str
                self.headers = _Headers(headers)

            def url_for(self, name: str) -> str:
                assert name == "oauth2_callback"
                return self._url

        return _Req(url, hdrs)

    def test_no_forwarded_headers_returns_url_for(self) -> None:
        req = self._fake_request()
        result = _build_callback_url(req, trust_forwarded=True)  # type: ignore[arg-type]
        assert result == "http://internal.local:8000/gw/dashboard/oauth2/callback"

    def test_rewrite_scheme_and_host_when_trust_forwarded(self) -> None:
        req = self._fake_request(
            forwarded_proto="https",
            forwarded_host="app.example.com",
        )
        result = _build_callback_url(req, trust_forwarded=True)  # type: ignore[arg-type]
        assert result == "https://app.example.com/gw/dashboard/oauth2/callback"

    def test_preserves_non_standard_port_in_forwarded_host(self) -> None:
        req = self._fake_request(
            forwarded_proto="https",
            forwarded_host="app.example.com:8443",
        )
        result = _build_callback_url(req, trust_forwarded=True)  # type: ignore[arg-type]
        assert result == "https://app.example.com:8443/gw/dashboard/oauth2/callback"

    def test_forwarded_headers_ignored_when_trust_forwarded_false(self) -> None:
        """SECURITY: the critical gate. A request carrying forwarded headers
        while trust_forwarded=False is treated as an attacker injecting them
        — the helper MUST NOT rewrite. Otherwise an attacker can steer the
        OAuth2 redirect_uri to their own host."""
        req = self._fake_request(
            forwarded_proto="https",
            forwarded_host="attacker.com",
        )
        result = _build_callback_url(req, trust_forwarded=False)  # type: ignore[arg-type]
        assert result == "http://internal.local:8000/gw/dashboard/oauth2/callback"
        assert "attacker.com" not in result

    def test_uses_first_value_from_comma_list(self) -> None:
        """Forwarded headers may contain a chain (``client, proxy1``). The
        first entry is the one closest to the client (per RFC 7239 spirit)."""
        req = self._fake_request(
            forwarded_proto="https, http",
            forwarded_host="app.example.com, internal.local",
        )
        result = _build_callback_url(req, trust_forwarded=True)  # type: ignore[arg-type]
        assert result == "https://app.example.com/gw/dashboard/oauth2/callback"


# ---------------------------------------------------------------------------
# F6 — SSE response headers on chat stream
# ---------------------------------------------------------------------------


class TestChatStreamSseHeaders:
    async def test_sse_headers_cleaned_up(self) -> None:
        """POST /dashboard/chat/stream from an authenticated session: response
        has ``Cache-Control: no-cache, no-transform`` and NO
        ``Connection: keep-alive``. The chat engine may emit an SSE error
        frame for the fixture workspace (nonexistent agent) — that's fine,
        we only care about the initial response headers which our handler
        constructs directly."""
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False, title="Test")
        gw.use_dashboard(
            auth_password="testpass",
            auth_username="testuser",
            admin_username="admin",
            admin_password="adminpass",
        )
        async with gw:
            _mock_repos(gw)
            client = await _client(gw)
            async with client:
                await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                async with client.stream(
                    "POST",
                    "/dashboard/chat/stream",
                    data={"message": "hello", "agent_id": "nonexistent"},
                ) as resp:
                    assert resp.status_code == 200, resp.status_code
                    ctype = resp.headers.get("content-type", "")
                    assert ctype.startswith("text/event-stream"), ctype
                    cache = resp.headers.get("cache-control", "")
                    assert "no-cache" in cache
                    assert "no-transform" in cache
                    header_keys = {k.lower() for k in resp.headers}
                    assert "connection" not in header_keys, (
                        f"Connection header must not be set on SSE response; "
                        f"found headers: {sorted(header_keys)}"
                    )


# ---------------------------------------------------------------------------
# Hot-reload: proxy config persists across gw.reload()
# ---------------------------------------------------------------------------


class TestHotReloadProxyConfig:
    async def test_proxy_config_persists_across_reload(self) -> None:
        """reload() rebuilds the workspace snapshot but does not reinstall
        middleware. The ``ProxyHeadersMiddleware`` instance already wired at
        startup keeps reading ``self._config.proxy``, so reload MUST NOT
        clobber it — even if use_proxy_headers() has been called again."""
        gw = _make_dashboard_gateway(trust_forwarded=True)
        async with gw:
            _mock_repos(gw)
            assert gw._config is not None
            assert gw._config.proxy.trust_forwarded is True
            await gw.reload()
            assert gw._config.proxy.trust_forwarded is True
            # Cookie still comes back Secure after reload.
            client = await _client(gw)
            async with client:
                resp = await client.post(
                    "/dashboard/login",
                    data={"username": "testuser", "password": "testpass"},
                    follow_redirects=False,
                )
                assert "secure" in resp.headers.get("set-cookie", "").lower()


# ---------------------------------------------------------------------------
# use_proxy_headers rejection after startup
# ---------------------------------------------------------------------------


class TestUseProxyHeadersGuards:
    async def test_cannot_call_after_started(self) -> None:
        import pytest

        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        async with gw:
            with pytest.raises(RuntimeError, match="after gateway has started"):
                gw.use_proxy_headers()
