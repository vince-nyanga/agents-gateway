"""Rate limiting integration via slowapi (optional dependency)."""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_gateway.config import RateLimitConfig

logger = logging.getLogger(__name__)

try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIASGIMiddleware
    from slowapi.util import get_remote_address

    HAS_SLOWAPI = True
except ImportError:  # pragma: no cover
    HAS_SLOWAPI = False


def _get_forwarded_key_func(request: Request) -> str:
    """Extract client IP from X-Forwarded-For header, falling back to remote address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # First IP in the chain is the original client
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


async def _rate_limit_exceeded_handler(request: Request, exc: Any) -> JSONResponse:
    """Return a 429 JSON response when the rate limit is exceeded."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"},
    )


class _StreamingSafeSlowAPIMiddleware:
    """Wraps SlowAPIASGIMiddleware to fix a bug where it re-sends http.response.start
    for every body chunk in streaming responses, violating the ASGI protocol."""

    def __init__(self, app: Any) -> None:
        self._inner = SlowAPIASGIMiddleware(app)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._inner(scope, receive, send)
            return

        started = False

        async def deduped_send(message: Any) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                if started:
                    return  # Drop duplicate — slowapi streaming bug workaround
                started = True
            await send(message)

        await self._inner(scope, receive, deduped_send)


def setup_rate_limiting(
    app: Any,
    config: RateLimitConfig,
) -> tuple[Any, type[Any]] | None:
    """Configure rate limiting on the given application.

    Returns a ``(limiter, middleware_class)`` tuple if slowapi is available,
    or ``None`` if the optional dependency is missing.
    """
    if not HAS_SLOWAPI:
        logger.warning(
            "Rate limiting is enabled but 'slowapi' is not installed. "
            "Install with: pip install agents-gateway[rate-limiting]"
        )
        return None

    key_func = _get_forwarded_key_func if config.trust_forwarded_for else get_remote_address

    limiter = Limiter(
        key_func=key_func,
        default_limits=[config.default_limit],
        headers_enabled=True,
        storage_uri=config.storage_uri or None,
    )

    # slowapi requires the limiter on app.state
    app.state.limiter = limiter

    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    return limiter, _StreamingSafeSlowAPIMiddleware
