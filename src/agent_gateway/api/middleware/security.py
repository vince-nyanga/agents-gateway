"""Pure ASGI security headers middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from agent_gateway.config import SecurityConfig

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class SecurityHeadersMiddleware:
    """Inject standard security headers into every HTTP response.

    Intercepts ``http.response.start`` ASGI messages and appends
    security headers before forwarding to the inner application.
    Dashboard paths receive a relaxed Content-Security-Policy to
    allow inline styles/scripts required by the UI.
    """

    def __init__(self, app: ASGIApp, config: SecurityConfig) -> None:
        self.app = app
        self._config = config
        # Pre-encode headers for performance (called on every response)
        self._base_headers: list[tuple[bytes, bytes]] = [
            (b"x-content-type-options", config.x_content_type_options.encode()),
            (b"x-frame-options", config.x_frame_options.encode()),
            (b"referrer-policy", config.referrer_policy.encode()),
        ]
        if config.strict_transport_security:
            self._base_headers.append(
                (b"strict-transport-security", config.strict_transport_security.encode())
            )
        self._api_csp = config.content_security_policy.encode()
        self._dashboard_csp = config.dashboard_content_security_policy.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        root_path: str = scope.get("root_path", "")
        if root_path and path.startswith(root_path):
            path = path[len(root_path) :]
        is_dashboard = path.startswith("/dashboard")

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._base_headers)
                # Use relaxed CSP for dashboard, strict for API
                csp = self._dashboard_csp if is_dashboard else self._api_csp
                headers.append((b"content-security-policy", csp))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
