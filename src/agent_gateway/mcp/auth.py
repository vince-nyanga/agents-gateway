"""OAuth2 token providers for MCP HTTP connections.

Core module -- zero new dependencies. Google-specific provider lives in
mcp/auth_google.py and is lazy-imported only when needed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any, Protocol, runtime_checkable

import httpx

from agent_gateway.exceptions import McpAuthError

logger = logging.getLogger(__name__)

# Refresh buffer: refresh token when < 5 minutes remain
_REFRESH_BUFFER_SECONDS = 300


@runtime_checkable
class McpTokenProvider(Protocol):
    """Protocol for async token providers.

    Implement this protocol to provide custom OAuth2 token refresh for
    MCP HTTP connections. Pass instances via add_mcp_server(token_provider=...).
    """

    server_name: str

    async def get_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        ...


class OAuth2ClientCredentialsProvider:
    """Token provider for OAuth2 client_credentials grant.

    Token caching strategy: always acquire the asyncio.Lock before reading
    mutable token state (_token, _expires_at). This avoids subtle races
    where a pre-lock read sees a stale token that another coroutine is
    about to overwrite. The lock is lightweight (no I/O) when the token
    is still fresh -- the only I/O happens inside _refresh().
    """

    def __init__(
        self,
        server_name: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        scopes: list[str] | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> None:
        self.server_name = server_name
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes or []
        self._extra_params = extra_params or {}
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a valid access token. Always acquires lock before reading state."""
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at - _REFRESH_BUFFER_SECONDS:
                return self._token
            return await self._refresh()

    async def _refresh(self) -> str:
        """Fetch a new token from the OAuth2 token endpoint.

        Raises McpAuthError on HTTP or parsing failures.
        """
        # TODO: Add exponential backoff on repeated refresh failures
        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scopes:
            data["scope"] = " ".join(self._scopes)
        data.update(self._extra_params)

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self._token_url, data=data)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            raise McpAuthError(
                f"OAuth2 client_credentials token refresh failed for "
                f"MCP server '{self.server_name}': {exc}",
                server_name=self.server_name,
            ) from exc

        try:
            self._token = body["access_token"]
        except KeyError:
            raise McpAuthError(
                f"OAuth2 response missing 'access_token' for MCP server '{self.server_name}'",
                server_name=self.server_name,
            ) from None

        expires_in = body.get("expires_in", 3600)
        self._expires_at = time.monotonic() + expires_in
        logger.debug(
            "OAuth2 client_credentials token refreshed for '%s', expires_in=%d",
            self.server_name,
            expires_in,
        )
        return self._token


class McpHttpAuth(httpx.Auth):
    """httpx.Auth subclass that delegates to an McpTokenProvider.

    Constructed and passed as ``httpx.AsyncClient(auth=McpHttpAuth(provider))``,
    which is then given to ``streamable_http_client(url, http_client=client)``.
    Every outgoing HTTP request gets a fresh Authorization: Bearer header.
    """

    def __init__(self, provider: McpTokenProvider) -> None:
        self._provider = provider

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token = await self._provider.get_token()
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


def build_auth_from_credentials(
    credentials: dict[str, Any],
    server_name: str,
) -> httpx.Auth | None:
    """Factory: build an httpx.Auth from decrypted credential dict.

    Returns None for static_header or legacy credentials (handled by static
    header logic in manager.py). Raises McpAuthError for unknown auth_type.

    The google_service_account path lazy-imports from mcp.auth_google to
    avoid pulling in google-auth unless actually needed.

    Args:
        credentials: Decrypted credential dict from McpServerConfig.
        server_name: MCP server name, passed to providers for error messages.
    """
    scopes = credentials.get("scopes")
    if scopes is not None and not isinstance(scopes, list):
        raise McpAuthError(
            f"'scopes' must be a list of strings, got {type(scopes).__name__}",
            server_name=server_name,
        )

    auth_type = credentials.get("auth_type")
    if auth_type is None or auth_type == "static_header":
        return None  # legacy path, handled by static header logic in manager

    if auth_type == "oauth2_client_credentials":
        provider = OAuth2ClientCredentialsProvider(
            server_name=server_name,
            token_url=credentials["token_url"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            scopes=credentials.get("scopes"),
            extra_params=credentials.get("extra_params"),
        )
        return McpHttpAuth(provider)

    if auth_type == "google_service_account":
        # Lazy import: only pulls in google-auth when this auth type is used.
        from agent_gateway.mcp.auth_google import GoogleServiceAccountProvider

        gcp_provider = GoogleServiceAccountProvider(
            server_name=server_name,
            service_account_info=credentials["service_account_json"],
            scopes=credentials.get("scopes", []),
        )
        return McpHttpAuth(gcp_provider)

    raise McpAuthError(
        f"Unknown MCP auth_type: {auth_type!r} for server '{server_name}'",
        server_name=server_name,
    )
