"""Shared error response helpers for API routes."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from agent_gateway.api.models import ErrorDetail, ErrorResponse


def error_response(
    status_code: int,
    code: str,
    message: str,
    execution_id: str | None = None,
) -> JSONResponse:
    """Build a standard error JSONResponse."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=code,
                message=message,
                execution_id=execution_id,
            )
        ).model_dump(),
    )


def not_found(resource_type: str, resource_id: str) -> JSONResponse:
    """Standard 404 response for a missing resource."""
    return error_response(
        404,
        f"{resource_type}_not_found",
        f"{resource_type.title()} '{resource_id}' not found",
    )
