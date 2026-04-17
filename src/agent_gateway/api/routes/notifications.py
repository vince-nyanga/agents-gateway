"""Notification delivery log endpoints."""

from fastapi import APIRouter, Depends, Query, Request

from agent_gateway.api.models import (
    NotificationDeliveryListResponse,
    NotificationDeliveryResponse,
)
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.auth.scopes import RequireScope

router = APIRouter(route_class=GatewayAPIRoute)


@router.get(
    "/notifications",
    response_model=NotificationDeliveryListResponse,
    summary="List notification deliveries",
    description="List notification delivery records with optional filtering.",
    tags=["Notifications"],
    dependencies=[Depends(RequireScope("notifications:read"))],
)
async def list_notifications(
    request: Request,
    status: str | None = Query(None, description="Filter by delivery status."),
    agent_id: str | None = Query(None, description="Filter by agent ID."),
    channel: str | None = Query(None, description="Filter by channel."),
    execution_id: str | None = Query(None, description="Filter by execution ID."),
    limit: int = Query(50, ge=1, le=200, description="Max records to return."),
    offset: int = Query(0, ge=0, description="Offset for pagination."),
) -> NotificationDeliveryListResponse:
    gw = request.app
    repo = gw._notification_repo

    records = await repo.list_recent(
        limit=limit,
        offset=offset,
        status=status,
        agent_id=agent_id,
        channel=channel,
        execution_id=execution_id,
    )
    total = await repo.count(
        status=status,
        agent_id=agent_id,
        channel=channel,
        execution_id=execution_id,
    )

    items = [
        NotificationDeliveryResponse(
            id=r.id or 0,
            execution_id=r.execution_id,
            agent_id=r.agent_id,
            event_type=r.event_type,
            channel=r.channel,
            target=r.target,
            status=r.status,
            attempts=r.attempts,
            last_error=r.last_error,
            created_at=r.created_at,
            delivered_at=r.delivered_at,
        )
        for r in records
    ]

    return NotificationDeliveryListResponse(items=items, total=total, limit=limit, offset=offset)
