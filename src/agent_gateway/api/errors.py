"""Shared error response helpers for API routes."""

from __future__ import annotations

from typing import Any

from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse, Response

from agent_gateway.api.models import ErrorDetail, ErrorResponse, FieldError


def error_response(
    status_code: int,
    code: str,
    message: str,
    execution_id: str | None = None,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """Build a standard error JSONResponse.

    ``details`` is optional — callers that raise framework-level
    ``RequestValidationError`` populate it with FastAPI's richer structure
    so generated clients can surface field-level issues. Backwards
    compatible: pre-existing callers pass only ``code`` / ``message``.
    """
    field_errors: list[FieldError] | None = None
    if details:
        field_errors = []
        for raw in details:
            loc = raw.get("loc", [])
            if not isinstance(loc, list | tuple):
                loc = [str(loc)]
            field_errors.append(
                FieldError(
                    loc=[str(part) if not isinstance(part, int) else part for part in loc],
                    msg=str(raw.get("msg", "")),
                    type=str(raw.get("type", "")),
                )
            )

    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=code,
                message=message,
                execution_id=execution_id,
                details=field_errors,
            )
        ).model_dump(exclude_none=True),
    )


def not_found(resource_type: str, resource_id: str) -> JSONResponse:
    """Standard 404 response for a missing resource."""
    return error_response(
        404,
        f"{resource_type}_not_found",
        f"{resource_type.title()} '{resource_id}' not found",
    )


async def per_agent_invoke_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> Response:
    """Custom 422 handler for per-agent typed invoke routes.

    FastAPI's default ``RequestValidationError`` envelope (``{"detail":
    [...]}``) differs from the gateway's standard envelope
    (``{"error": {"code": ..., "message": ...}}``). Existing clients reading
    ``error.code == "input_validation_failed"`` would break if we leaked the
    default for per-agent routes. This handler rewraps the error for paths
    that are registered per-agent invoke routes and delegates to FastAPI's
    default for everything else.
    """
    paths: set[str] = getattr(request.app, "_per_agent_invoke_paths", set())
    # Match on the matched route's bare path (no mount prefix, no parent
    # mount). ``request.url.path`` includes any mount prefix, so comparing
    # against it would fail under mount_to(). ``request.scope["route"]``
    # is set by Starlette once a route is matched; for per-agent routes it
    # is an APIRoute whose .path is the gateway-local path we track.
    route = request.scope.get("route")
    route_path: str | None = getattr(route, "path", None) if route is not None else None
    if route_path is None or route_path not in paths:
        return await request_validation_exception_handler(request, exc)

    errors = exc.errors()
    message_parts: list[str] = []
    for err in errors:
        loc_parts = [str(p) for p in err.get("loc", [])]
        loc_str = ".".join(loc_parts)
        msg = str(err.get("msg", ""))
        message_parts.append(f"{loc_str}: {msg}" if loc_str else msg)

    summary = "; ".join(message_parts) if message_parts else "Invalid request body"
    return error_response(
        422,
        "input_validation_failed",
        f"Input validation failed: {summary}",
        details=list(errors),
    )
