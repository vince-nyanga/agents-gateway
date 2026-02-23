"""Introspection endpoints — list agents, skills, tools, and trigger reload."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.errors import error_response, not_found
from agent_gateway.api.models import (
    AgentInfo,
    NotificationConfigInfo,
    NotificationTargetInfo,
    SkillInfo,
    ToolInfo,
)
from agent_gateway.api.openapi import build_responses
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.auth.scopes import RequireScope

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway
    from agent_gateway.workspace.agent import AgentDefinition

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)

_ID_PATTERN = r"^[a-zA-Z0-9_.-]+$"


def _build_notification_config(agent: AgentDefinition) -> NotificationConfigInfo | None:
    """Build notification config info for introspection, or None if unconfigured."""
    cfg = agent.notifications
    if not cfg.on_complete and not cfg.on_error and not cfg.on_timeout:
        return None
    return NotificationConfigInfo(
        on_complete=[
            NotificationTargetInfo(channel=t.channel, target=t.target) for t in cfg.on_complete
        ],
        on_error=[
            NotificationTargetInfo(channel=t.channel, target=t.target) for t in cfg.on_error
        ],
        on_timeout=[
            NotificationTargetInfo(channel=t.channel, target=t.target) for t in cfg.on_timeout
        ],
    )


@router.get(
    "/agents",
    response_model=list[AgentInfo],
    summary="List agents",
    description="List all discovered agents and their configurations.",
    tags=["Agents"],
    responses=build_responses(auth=True),
    dependencies=[Depends(RequireScope("agents:read"))],
)
async def list_agents(request: Request) -> list[AgentInfo]:
    """List all discovered agents."""
    gw: Gateway = request.app
    ws = gw.workspace
    if ws is None:
        return []

    return [
        AgentInfo(
            id=agent.id,
            description=agent.description if agent.description else f"Agent: {agent.id}",
            display_name=agent.display_name,
            tags=agent.tags,
            version=agent.version,
            skills=agent.skills,
            tools=ws.resolve_agent_tools(agent),
            model=agent.model.name,
            schedules=[s.name for s in agent.schedules],
            execution_mode=agent.execution_mode,
            notifications=_build_notification_config(agent),
            input_schema=agent.input_schema,
            retrievers=agent.retrievers,
            context_file_count=len(agent.context_content),
            memory_enabled=bool(agent.memory_config and agent.memory_config.enabled),
        )
        for agent in ws.agents.values()
    ]


@router.get(
    "/agents/{agent_id}",
    response_model=AgentInfo,
    summary="Get agent details",
    description="Get detailed information about a specific agent.",
    tags=["Agents"],
    responses=build_responses(auth=True, not_found=True),
    dependencies=[Depends(RequireScope("agents:read"))],
)
async def get_agent(
    request: Request,
    agent_id: str = Path(..., min_length=1, max_length=128, pattern=_ID_PATTERN),
) -> AgentInfo | JSONResponse:
    """Get details of a specific agent."""
    gw: Gateway = request.app
    ws = gw.workspace
    if ws is None:
        return not_found("agent", agent_id)

    agent = ws.agents.get(agent_id)
    if agent is None:
        return not_found("agent", agent_id)

    return AgentInfo(
        id=agent.id,
        description=agent.description if agent.description else f"Agent: {agent.id}",
        display_name=agent.display_name,
        tags=agent.tags,
        version=agent.version,
        skills=agent.skills,
        tools=ws.resolve_agent_tools(agent),
        model=agent.model.name,
        schedules=[s.name for s in agent.schedules],
        execution_mode=agent.execution_mode,
        notifications=_build_notification_config(agent),
        input_schema=agent.input_schema,
        retrievers=agent.retrievers,
        context_file_count=len(agent.context_content),
    )


@router.get(
    "/skills",
    response_model=list[SkillInfo],
    summary="List skills",
    description="List all discovered skills and their configurations.",
    tags=["Skills"],
    responses=build_responses(auth=True),
    dependencies=[Depends(RequireScope("agents:read"))],
)
async def list_skills(request: Request) -> list[SkillInfo]:
    """List all discovered skills."""
    gw: Gateway = request.app
    ws = gw.workspace
    if ws is None:
        return []

    return [
        SkillInfo(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            tools=skill.tools,
            has_workflow=skill.has_workflow,
            step_count=len(skill.steps),
        )
        for skill in ws.skills.values()
    ]


@router.get(
    "/skills/{skill_id}",
    response_model=SkillInfo,
    summary="Get skill details",
    description="Get detailed information about a specific skill.",
    tags=["Skills"],
    responses=build_responses(auth=True, not_found=True),
    dependencies=[Depends(RequireScope("agents:read"))],
)
async def get_skill(
    request: Request,
    skill_id: str = Path(..., min_length=1, max_length=128, pattern=_ID_PATTERN),
) -> SkillInfo | JSONResponse:
    """Get details of a specific skill."""
    gw: Gateway = request.app
    ws = gw.workspace
    if ws is None:
        return not_found("skill", skill_id)

    skill = ws.skills.get(skill_id)
    if skill is None:
        return not_found("skill", skill_id)

    return SkillInfo(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        tools=skill.tools,
        has_workflow=skill.has_workflow,
        step_count=len(skill.steps),
    )


@router.get(
    "/tools",
    response_model=list[ToolInfo],
    summary="List tools",
    description="List all registered tools (file-based and code-based).",
    tags=["Tools"],
    responses=build_responses(auth=True),
    dependencies=[Depends(RequireScope("agents:read"))],
)
async def list_tools(request: Request) -> list[ToolInfo]:
    """List all registered tools (file-based + code-based)."""
    gw: Gateway = request.app
    reg = gw.tool_registry
    if reg is None:
        return []

    return [
        ToolInfo(
            name=tool.name,
            description=tool.description,
            source=tool.source,
            parameters=tool.parameters_schema,
        )
        for tool in reg.get_all().values()
    ]


@router.get(
    "/tools/{tool_id}",
    response_model=ToolInfo,
    summary="Get tool details",
    description="Get detailed information about a specific tool.",
    tags=["Tools"],
    responses=build_responses(auth=True, not_found=True),
    dependencies=[Depends(RequireScope("agents:read"))],
)
async def get_tool(
    request: Request,
    tool_id: str = Path(..., min_length=1, max_length=128, pattern=_ID_PATTERN),
) -> ToolInfo | JSONResponse:
    """Get details of a specific tool."""
    gw: Gateway = request.app
    reg = gw.tool_registry
    if reg is None:
        return not_found("tool", tool_id)

    tool = reg.get(tool_id)
    if tool is None:
        return not_found("tool", tool_id)

    return ToolInfo(
        name=tool.name,
        description=tool.description,
        source=tool.source,
        parameters=tool.parameters_schema,
    )


@router.post(
    "/reload",
    summary="Reload workspace",
    description=(
        "Re-scan the workspace directory and reload all agent, skill, and tool definitions."
    ),
    tags=["Admin"],
    responses=build_responses(auth=True),
    dependencies=[Depends(RequireScope("admin"))],
)
async def reload_workspace(request: Request) -> JSONResponse:
    """Re-scan workspace and reload all definitions."""
    gw: Gateway = request.app

    if not gw._reload_enabled:
        return error_response(403, "reload_disabled", "Workspace reload is disabled")

    try:
        await gw.reload()
        ws = gw.workspace
        agent_count = len(ws.agents) if ws else 0
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "agents": agent_count,
                "message": "Workspace reloaded successfully",
            },
        )
    except Exception:
        logger.error("Workspace reload failed", exc_info=True)
        return error_response(500, "reload_failed", "Workspace reload failed")
