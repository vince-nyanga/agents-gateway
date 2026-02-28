"""Google Cloud service account token provider for MCP HTTP connections.

Requires: pip install agent-gateway[gcp]

This module is lazy-imported by build_auth_from_credentials() in mcp/auth.py
only when auth_type is "google_service_account". It is never imported at
module level, so google-auth is not required unless actually used.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from agent_gateway.exceptions import McpAuthError
from agent_gateway.mcp.auth import _REFRESH_BUFFER_SECONDS

try:
    import google.auth.transport.requests as google_requests
    from google.oauth2 import service_account as sa
except ImportError:
    sa = None
    google_requests = None

logger = logging.getLogger(__name__)


class GoogleServiceAccountProvider:
    """Token provider using google-auth service account credentials.

    Token caching strategy: always acquire the asyncio.Lock before reading
    credential state. The google-auth Credentials object is mutable and not
    thread-safe, so we protect all reads behind the lock.
    """

    def __init__(
        self,
        server_name: str,
        service_account_info: dict[str, Any],
        scopes: list[str],
    ) -> None:
        if sa is None:
            raise ImportError(
                "google-auth is required for Google service account auth. "
                "Install with: pip install agent-gateway[gcp]"
            )

        self.server_name = server_name
        self._credentials: Any = sa.Credentials.from_service_account_info(
            service_account_info, scopes=scopes
        )
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a valid access token. Always acquires lock before reading state."""
        async with self._lock:
            if (
                self._credentials.valid
                and self._credentials.token
                and self._credentials.expiry
                and (self._credentials.expiry.timestamp() - time.time()) > _REFRESH_BUFFER_SECONDS
            ):
                return str(self._credentials.token)
            return await self._refresh()

    async def _refresh(self) -> str:
        """Refresh the service account token.

        google-auth's refresh() is synchronous and does network I/O,
        so we run it in an executor to avoid blocking the event loop.
        Raises McpAuthError on failure.
        """
        # TODO: Add exponential backoff on repeated refresh failures
        loop = asyncio.get_running_loop()
        request = google_requests.Request()
        try:
            await loop.run_in_executor(None, self._credentials.refresh, request)
        except Exception as exc:
            raise McpAuthError(
                f"Google SA token refresh failed for MCP server '{self.server_name}': {exc}",
                server_name=self.server_name,
            ) from exc

        # None-guard: google-auth can leave .token as None after refresh
        # in edge cases (e.g., credential misconfiguration, universe domain
        # mismatch). Fail fast with a clear error rather than passing None
        # downstream as a Bearer token.
        if self._credentials.token is None:
            raise McpAuthError(
                f"Google SA token is None after refresh for "
                f"MCP server '{self.server_name}'. Check service account "
                f"configuration and scopes.",
                server_name=self.server_name,
            )

        logger.debug(
            "Google SA token refreshed for '%s', expiry=%s",
            self.server_name,
            self._credentials.expiry,
        )
        return str(self._credentials.token)
