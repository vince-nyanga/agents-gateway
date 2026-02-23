"""OpenAPI documentation helpers."""

from __future__ import annotations

from typing import Any

from agent_gateway.api.models import ErrorResponse

_ERROR_SCHEMA: dict[str, Any] = {"model": ErrorResponse}


def build_responses(
    *,
    auth: bool = False,
    not_found: bool = False,
    conflict: bool = False,
    rate_limit: bool = False,
) -> dict[int | str, dict[str, Any]]:
    """Build a combined responses dict for OpenAPI route decorators."""
    result: dict[int | str, dict[str, Any]] = {}
    if auth:
        result[401] = {"description": "Authentication required", **_ERROR_SCHEMA}
        result[403] = {"description": "Insufficient permissions", **_ERROR_SCHEMA}
    if not_found:
        result[404] = {"description": "Resource not found", **_ERROR_SCHEMA}
    if conflict:
        result[409] = {"description": "Conflict — invalid state transition", **_ERROR_SCHEMA}
    if rate_limit:
        result[429] = {"description": "Rate limit exceeded", **_ERROR_SCHEMA}
    return result
