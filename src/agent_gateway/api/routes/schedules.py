"""Schedule management endpoints — list, pause, resume, trigger schedules."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.errors import error_response, not_found
from agent_gateway.api.models import ScheduleDetailInfo, ScheduleInfo
from agent_gateway.api.openapi import build_responses
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.auth.scopes import RequireScope

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)

_SCHEDULE_ID_PATTERN = r"^[a-zA-Z0-9_.:/-]+$"


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
    gw: Gateway = request.app
    schedules = await gw.list_schedules()
    return [ScheduleInfo(**s) for s in schedules]


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
    gw: Gateway = request.app
    detail = await gw.get_schedule(schedule_id)
    if detail is None:
        return not_found("schedule", schedule_id)

    return ScheduleDetailInfo(**detail)


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
    gw: Gateway = request.app
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
    gw: Gateway = request.app
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
    gw: Gateway = request.app
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
