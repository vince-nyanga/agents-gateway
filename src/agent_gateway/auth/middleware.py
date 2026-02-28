"""Pure ASGI authentication middleware — no BaseHTTPMiddleware dependency."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from agent_gateway.auth.protocols import AuthProvider

# ASGI types
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class AuthMiddleware:
    """Pure ASGI auth middleware.

    Responsibilities:
    1. Extract Bearer token from Authorization header
    2. Delegate to AuthProvider for token validation
    3. Store AuthResult in scope["auth"] for downstream access
    4. Return 401 JSON errors for failed auth
    5. Skip auth for non-/v1/ paths and configured public paths
    """

    def __init__(
        self,
        app: ASGIApp,
        provider: AuthProvider,
        public_paths: frozenset[str] = frozenset({"/v1/health"}),
    ) -> None:
        self.app = app
        self.provider = provider
        self.public_paths = public_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only intercept HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        root_path: str = scope.get("root_path", "")
        if root_path and path.startswith(root_path):
            path = path[len(root_path) :]

        # Custom routes and public paths bypass auth
        if not path.startswith("/v1/") or path in self.public_paths:
            await self.app(scope, receive, send)
            return

        token = self._extract_bearer_token(scope)
        if token is None:
            await self._send_error(
                send,
                401,
                "auth_required",
                "Missing or invalid Authorization header. Expected: Bearer <token>",
            )
            return

        result = await self.provider.authenticate(token)
        if not result.authenticated:
            await self._send_error(
                send,
                401,
                "invalid_credentials",
                result.error or "Invalid credentials",
            )
            return

        # Store auth context for downstream handlers
        scope["auth"] = result
        await self.app(scope, receive, send)

    @staticmethod
    def _extract_bearer_token(scope: Scope) -> str | None:
        """Extract Bearer token from raw ASGI headers."""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                decoded = value.decode("latin-1")
                if decoded.startswith("Bearer "):
                    token: str = decoded[7:]
                    return token
                return None
        return None

    @staticmethod
    async def _send_error(send: Send, status: int, code: str, message: str) -> None:
        """Send a JSON error response with WWW-Authenticate header."""
        body = json.dumps({"error": {"code": code, "message": message}}).encode()
        headers: list[list[bytes]] = [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
            [b"www-authenticate", b"Bearer"],
        ]
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
