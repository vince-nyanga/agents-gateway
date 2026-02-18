"""Health check endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from agent_gateway.api.models import HealthResponse

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

from agent_gateway.api.routes.base import GatewayAPIRoute

router = APIRouter(route_class=GatewayAPIRoute)


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """Return gateway health status, startup errors, and resource counts."""
    gw: Gateway = request.app  # type: ignore[assignment]

    workspace = gw._workspace
    errors = workspace.errors if workspace else ["Workspace not loaded"]
    warnings = workspace.warnings if workspace else []

    agent_count = len(workspace.agents) if workspace else 0
    skill_count = len(workspace.skills) if workspace else 0
    tool_count = len(gw._tool_registry.get_all()) if gw._tool_registry else 0

    status = "ok" if not errors else "degraded"

    return HealthResponse(
        status=status,
        agent_count=agent_count,
        skill_count=skill_count,
        tool_count=tool_count,
        workspace_path=str(gw._workspace_path),
        startup_errors=errors,
        startup_warnings=warnings,
    )
