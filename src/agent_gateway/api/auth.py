"""API key authentication middleware for the gateway."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from fastapi import FastAPI

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/v1/health"})


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Validates API key from Authorization header against configured keys.

    When auth is enabled, all /v1/ endpoints (except health) require
    a valid ``Authorization: Bearer <key>`` header.
    """

    def __init__(self, app: FastAPI, valid_keys: dict[str, list[str]]) -> None:
        """Initialize with a mapping of key -> scopes."""
        super().__init__(app)
        self._valid_keys = valid_keys  # {key_value: [scopes]}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip auth for non-API and public paths
        if not path.startswith("/v1/") or path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "auth_required",
                        "message": "Missing or invalid Authorization header."
                        " Expected: Bearer <api_key>",
                    }
                },
            )

        api_key = auth_header[7:]  # strip "Bearer "
        scopes = self._valid_keys.get(api_key)
        if scopes is None:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "invalid_api_key",
                        "message": "Invalid API key",
                    }
                },
            )

        # Store scopes on request state for downstream use
        request.state.auth_scopes = scopes
        return await call_next(request)
