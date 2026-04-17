"""Schedule management endpoints — list, pause, resume, trigger, create, delete schedules."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent_gateway.api.errors import error_response, not_found
from agent_gateway.api.models import ScheduleDetailInfo, ScheduleInfo
from agent_gateway.api.openapi import build_responses
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.auth.scopes import RequireScope

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)

_SCHEDULE_ID_PATTERN = r"^[a-zA-Z0-9_.:/-]+$"


class CreateScheduleRequest(BaseModel):
    """Request body for creating an admin schedule."""

    agent_id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.\-]+$")
    cron_expr: str = Field(..., min_length=9, max_length=128)
    message: str = Field(..., min_length=1, max_length=102_400)
    instructions: str | None = Field(None, max_length=4000)
    input: dict[str, Any] = Field(default_factory=dict)
    timezone: str = Field("UTC", max_length=64)
    enabled: bool = True


@router.get(
    "/schedules",
    response_model=list[ScheduleInfo],
    summary="List schedules",
    description="List all registered cron schedules.",
    tags=["Schedules"],
    responses=build_responses(auth=True),
    dependencies=[Depends(RequireScope("schedules:read"))],
)
async def list_schedules(request: Request) -> list[ScheduleInfo]:
    """List all registered schedules."""
    gw = request.app
    schedules = await gw.list_schedules()
    return [ScheduleInfo(**s) for s in schedules]


@router.post(
    "/schedules",
    summary="Create admin schedule",
    description="Create a new admin-managed schedule for an agent.",
    tags=["Schedules"],
    responses={
        201: {"description": "Schedule created."},
        400: {"description": "Invalid schedule configuration."},
        409: {"description": "Schedule with this name already exists."},
        **build_responses(auth=True, not_found=True),
    },
    dependencies=[Depends(RequireScope("schedules:manage"))],
)
async def create_schedule(
    request: Request,
    body: CreateScheduleRequest,
) -> JSONResponse:
    """Create a new admin schedule."""
    from agent_gateway.exceptions import ScheduleConflictError, ScheduleValidationError

    gw = request.app
    if gw.scheduler is None:
        return error_response(404, "scheduler_not_active", "Scheduler is not active")

    # Validate agent exists at route level as UX guard
    if body.agent_id not in gw.agents:
        return not_found("agent", body.agent_id)

    try:
        schedule_id = await gw.create_admin_schedule(
            agent_id=body.agent_id,
            name=body.name,
            cron_expr=body.cron_expr,
            message=body.message,
            instructions=body.instructions,
            input_data=body.input,
            timezone=body.timezone,
            enabled=body.enabled,
        )
    except ScheduleValidationError as e:
        return error_response(400, "schedule_validation_error", str(e))
    except ScheduleConflictError as e:
        return error_response(409, "schedule_conflict", str(e))

    return JSONResponse(
        status_code=201,
        content={"status": "created", "schedule_id": schedule_id},
    )


@router.get(
    "/schedules/{schedule_id:path}",
    response_model=ScheduleDetailInfo,
    summary="Get schedule details",
    description="Get detailed information about a specific schedule.",
    tags=["Schedules"],
    responses=build_responses(auth=True, not_found=True),
    dependencies=[Depends(RequireScope("schedules:read"))],
)
async def get_schedule(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=256, pattern=_SCHEDULE_ID_PATTERN),
) -> ScheduleDetailInfo | JSONResponse:
    """Get details of a specific schedule."""
    gw = request.app
    detail = await gw.get_schedule(schedule_id)
    if detail is None:
        return not_found("schedule", schedule_id)

    return ScheduleDetailInfo(**detail)


@router.delete(
    "/schedules/{schedule_id:path}",
    summary="Delete admin schedule",
    description="Delete an admin-created schedule. Workspace schedules cannot be deleted.",
    tags=["Schedules"],
    responses={
        200: {"description": "Schedule deleted."},
        400: {"description": "Cannot delete a workspace schedule."},
        **build_responses(auth=True, not_found=True),
    },
    dependencies=[Depends(RequireScope("schedules:manage"))],
)
async def delete_schedule(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=256, pattern=_SCHEDULE_ID_PATTERN),
) -> JSONResponse:
    """Delete an admin-created schedule."""
    gw = request.app
    if gw.scheduler is None:
        return error_response(404, "scheduler_not_active", "Scheduler is not active")

    # Check if schedule exists and its source
    detail = await gw.get_schedule(schedule_id)
    if detail is None:
        return not_found("schedule", schedule_id)

    if detail.get("source") != "admin":
        return error_response(
            400,
            "cannot_delete_workspace_schedule",
            "Workspace schedules cannot be deleted. Remove them from AGENT.md instead.",
        )

    ok = await gw.delete_admin_schedule(schedule_id)
    if not ok:
        return not_found("schedule", schedule_id)

    return JSONResponse(
        status_code=200,
        content={"status": "deleted", "schedule_id": schedule_id},
    )


@router.post(
    "/schedules/{schedule_id:path}/pause",
    summary="Pause schedule",
    description="Pause a schedule to stop future cron fires.",
    tags=["Schedules"],
    responses=build_responses(auth=True, not_found=True),
    dependencies=[Depends(RequireScope("schedules:manage"))],
)
async def pause_schedule(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=256, pattern=_SCHEDULE_ID_PATTERN),
) -> JSONResponse:
    """Pause a schedule (stops future cron fires)."""
    gw = request.app
    if gw.scheduler is None:
        return error_response(404, "scheduler_not_active", "Scheduler is not active")

    ok = await gw.pause_schedule(schedule_id)
    if not ok:
        return not_found("schedule", schedule_id)

    return JSONResponse(
        status_code=200,
        content={"status": "paused", "schedule_id": schedule_id},
    )


@router.post(
    "/schedules/{schedule_id:path}/resume",
    summary="Resume schedule",
    description="Resume a previously paused schedule.",
    tags=["Schedules"],
    responses=build_responses(auth=True, not_found=True),
    dependencies=[Depends(RequireScope("schedules:manage"))],
)
async def resume_schedule(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=256, pattern=_SCHEDULE_ID_PATTERN),
) -> JSONResponse:
    """Resume a paused schedule."""
    gw = request.app
    if gw.scheduler is None:
        return error_response(404, "scheduler_not_active", "Scheduler is not active")

    ok = await gw.resume_schedule(schedule_id)
    if not ok:
        return not_found("schedule", schedule_id)

    return JSONResponse(
        status_code=200,
        content={"status": "resumed", "schedule_id": schedule_id},
    )


@router.post(
    "/schedules/{schedule_id:path}/trigger",
    summary="Trigger schedule",
    description="Manually trigger a scheduled job to run immediately.",
    tags=["Schedules"],
    responses={
        202: {"description": "Accepted — job queued. Returns execution_id for polling."},
        **build_responses(auth=True, not_found=True),
    },
    dependencies=[Depends(RequireScope("schedules:manage"))],
)
async def trigger_schedule(
    request: Request,
    schedule_id: str = Path(..., min_length=1, max_length=256, pattern=_SCHEDULE_ID_PATTERN),
) -> JSONResponse:
    """Manually trigger a scheduled job (runs immediately)."""
    gw = request.app
    if gw.scheduler is None:
        return error_response(404, "scheduler_not_active", "Scheduler is not active")

    execution_id = await gw.trigger_schedule(schedule_id)
    if execution_id is None:
        return not_found("schedule", schedule_id)

    return JSONResponse(
        status_code=202,
        content={
            "status": "triggered",
            "schedule_id": schedule_id,
            "execution_id": execution_id,
        },
    )
