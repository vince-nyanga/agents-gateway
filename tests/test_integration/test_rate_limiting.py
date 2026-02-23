"""Tests for rate limiting middleware integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent_gateway.gateway import Gateway

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURE_WORKSPACE = FIXTURES_DIR / "workspace"


def _make_gateway(*, rate_limit_enabled: bool = True, **rate_limit_kwargs: object) -> Gateway:
    gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
    if rate_limit_enabled:
        gw.use_rate_limit(**rate_limit_kwargs)  # type: ignore[arg-type]
    return gw


class TestRateLimitDisabled:
    async def test_no_rate_limit_headers_when_disabled(self) -> None:
        gw = _make_gateway(rate_limit_enabled=False)
        async with gw:
            transport = ASGITransport(app=gw)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/health")
                assert resp.status_code == 200
                # No rate limit headers when disabled
                assert "x-ratelimit-limit" not in resp.headers


class TestRateLimitEnabled:
    async def test_requests_within_limit_succeed(self) -> None:
        gw = _make_gateway(default_limit="10/minute")
        async with gw:
            transport = ASGITransport(app=gw)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/health")
                assert resp.status_code == 200

    async def test_requests_beyond_limit_return_429(self) -> None:
        gw = _make_gateway(default_limit="3/minute")
        async with gw:
            transport = ASGITransport(app=gw)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                for _ in range(3):
                    resp = await ac.get("/v1/health")
                    assert resp.status_code == 200

                resp = await ac.get("/v1/health")
                assert resp.status_code == 429
                assert resp.json() == {"detail": "Rate limit exceeded"}


class TestTrustForwardedFor:
    async def test_forwarded_for_uses_header_for_key(self) -> None:
        gw = _make_gateway(default_limit="2/minute", trust_forwarded_for=True)
        async with gw:
            transport = ASGITransport(app=gw)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                # Exhaust limit for client A
                for _ in range(2):
                    resp = await ac.get(
                        "/v1/health",
                        headers={"X-Forwarded-For": "1.2.3.4"},
                    )
                    assert resp.status_code == 200

                # Client A should be rate limited
                resp = await ac.get(
                    "/v1/health",
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
                assert resp.status_code == 429

                # Client B should still be allowed
                resp = await ac.get(
                    "/v1/health",
                    headers={"X-Forwarded-For": "5.6.7.8"},
                )
                assert resp.status_code == 200


class TestUseRateLimitApi:
    def test_use_rate_limit_enables_rate_limiting(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        gw.use_rate_limit(default_limit="50/minute")
        assert gw._pending_rate_limit_config is not None
        assert gw._pending_rate_limit_config.enabled is True
        assert gw._pending_rate_limit_config.default_limit == "50/minute"

    def test_use_rate_limit_returns_self(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        result = gw.use_rate_limit()
        assert result is gw

    async def test_use_rate_limit_after_start_raises(self) -> None:
        gw = Gateway(workspace=str(FIXTURE_WORKSPACE), auth=False)
        async with gw:
            with pytest.raises(RuntimeError, match="Cannot configure rate limiting"):
                gw.use_rate_limit()
