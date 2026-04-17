"""Health check endpoint."""

from fastapi import APIRouter, Request

from agent_gateway.api.models import HealthResponse
from agent_gateway.api.routes.base import GatewayAPIRoute

router = APIRouter(route_class=GatewayAPIRoute)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Return gateway health status and resource counts.",
    tags=["Health"],
)
async def health_check(request: Request) -> HealthResponse:
    """Return gateway health status and resource counts."""
    gw = request.app

    ws = gw.workspace
    has_errors = bool(ws.errors) if ws else True

    agent_count = len(ws.agents) if ws else 0
    skill_count = len(ws.skills) if ws else 0
    tool_count = len(gw.tools)

    return HealthResponse(
        status="degraded" if has_errors else "ok",
        agent_count=agent_count,
        skill_count=skill_count,
        tool_count=tool_count,
    )
