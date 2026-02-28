"""Tests for mcp/auth.py -- OAuth2 token providers and auth flow."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_gateway.exceptions import McpAuthError
from agent_gateway.mcp.auth import (
    McpHttpAuth,
    McpTokenProvider,
    OAuth2ClientCredentialsProvider,
    build_auth_from_credentials,
)

# ---------------------------------------------------------------------------
# McpTokenProvider protocol
# ---------------------------------------------------------------------------


class _CustomProvider:
    """User-defined class that satisfies the McpTokenProvider protocol."""

    def __init__(self) -> None:
        self.server_name = "custom-server"

    async def get_token(self) -> str:
        return "custom-token"


class TestMcpTokenProviderProtocol:
    def test_custom_provider_satisfies_protocol(self) -> None:
        provider = _CustomProvider()
        assert isinstance(provider, McpTokenProvider)

    def test_non_provider_fails_check(self) -> None:
        assert not isinstance(object(), McpTokenProvider)


# ---------------------------------------------------------------------------
# OAuth2ClientCredentialsProvider
# ---------------------------------------------------------------------------


class TestOAuth2ClientCredentialsProvider:
    def _make_provider(self) -> OAuth2ClientCredentialsProvider:
        return OAuth2ClientCredentialsProvider(
            server_name="test-server",
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csecret",
            scopes=["scope1", "scope2"],
        )

    @pytest.fixture
    def mock_response(self) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}
        return resp

    async def test_initial_fetch(self, mock_response: MagicMock) -> None:
        provider = self._make_provider()
        with patch("agent_gateway.mcp.auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            token = await provider.get_token()

        assert token == "tok123"
        mock_client.post.assert_called_once()

    async def test_cached_token(self, mock_response: MagicMock) -> None:
        provider = self._make_provider()
        with patch("agent_gateway.mcp.auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            t1 = await provider.get_token()
            t2 = await provider.get_token()

        assert t1 == t2 == "tok123"
        assert mock_client.post.call_count == 1  # only one HTTP call

    async def test_refresh_on_expiry(self, mock_response: MagicMock) -> None:
        provider = self._make_provider()
        with patch("agent_gateway.mcp.auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await provider.get_token()

            # Simulate expiry by setting _expires_at to now
            provider._expires_at = time.monotonic()

            await provider.get_token()

        assert mock_client.post.call_count == 2

    async def test_concurrent_refresh(self, mock_response: MagicMock) -> None:
        provider = self._make_provider()
        call_count = 0

        async def slow_post(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return mock_response

        with patch("agent_gateway.mcp.auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = slow_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            tokens = await asyncio.gather(
                provider.get_token(),
                provider.get_token(),
                provider.get_token(),
            )

        assert all(t == "tok123" for t in tokens)
        assert call_count == 1  # lock ensures single refresh

    async def test_http_error_raises_mcp_auth_error(self) -> None:
        provider = self._make_provider()
        with patch("agent_gateway.mcp.auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock()
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(McpAuthError, match="token refresh failed"):
                await provider.get_token()

    async def test_missing_access_token_raises_mcp_auth_error(self) -> None:
        provider = self._make_provider()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"token_type": "bearer"}  # no access_token

        with patch("agent_gateway.mcp.auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(McpAuthError, match="missing 'access_token'"):
                await provider.get_token()


# ---------------------------------------------------------------------------
# McpHttpAuth
# ---------------------------------------------------------------------------


class TestMcpHttpAuth:
    async def test_injects_bearer_header(self) -> None:
        provider = _CustomProvider()
        auth = McpHttpAuth(provider)

        request = httpx.Request("GET", "https://example.com")
        flow = auth.async_auth_flow(request)
        modified_request = await flow.__anext__()

        assert modified_request.headers["Authorization"] == "Bearer custom-token"

    async def test_refreshes_token(self) -> None:
        provider = MagicMock()
        provider.server_name = "srv"
        provider.get_token = AsyncMock(return_value="refreshed")
        auth = McpHttpAuth(provider)

        request = httpx.Request("GET", "https://example.com")
        flow = auth.async_auth_flow(request)
        await flow.__anext__()

        provider.get_token.assert_called_once()


# ---------------------------------------------------------------------------
# build_auth_from_credentials
# ---------------------------------------------------------------------------


class TestBuildAuthFromCredentials:
    def test_none_for_legacy_creds(self) -> None:
        result = build_auth_from_credentials({"bearer_token": "xyz"}, server_name="srv")
        assert result is None

    def test_none_for_static_header(self) -> None:
        result = build_auth_from_credentials(
            {"auth_type": "static_header", "bearer_token": "xyz"}, server_name="srv"
        )
        assert result is None

    def test_client_credentials(self) -> None:
        result = build_auth_from_credentials(
            {
                "auth_type": "oauth2_client_credentials",
                "token_url": "https://auth.example.com/token",
                "client_id": "cid",
                "client_secret": "csecret",
            },
            server_name="srv",
        )
        assert isinstance(result, McpHttpAuth)

    def test_unknown_auth_type_raises_mcp_auth_error(self) -> None:
        with pytest.raises(McpAuthError, match="Unknown MCP auth_type"):
            build_auth_from_credentials({"auth_type": "magic_beans"}, server_name="srv")

    def test_server_name_propagated(self) -> None:
        result = build_auth_from_credentials(
            {
                "auth_type": "oauth2_client_credentials",
                "token_url": "https://auth.example.com/token",
                "client_id": "cid",
                "client_secret": "csecret",
            },
            server_name="my-server",
        )
        assert isinstance(result, McpHttpAuth)
        assert result._provider.server_name == "my-server"

    def test_google_sa_lazy_import(self) -> None:
        """Verifies that google_service_account path imports auth_google."""
        with patch("agent_gateway.mcp.auth_google.GoogleServiceAccountProvider") as mock_provider:
            mock_instance = MagicMock()
            mock_instance.server_name = "srv"
            mock_provider.return_value = mock_instance

            result = build_auth_from_credentials(
                {
                    "auth_type": "google_service_account",
                    "service_account_json": {"type": "service_account"},
                    "scopes": ["https://www.googleapis.com/auth/bigquery"],
                },
                server_name="srv",
            )

        assert isinstance(result, McpHttpAuth)
        mock_provider.assert_called_once()
