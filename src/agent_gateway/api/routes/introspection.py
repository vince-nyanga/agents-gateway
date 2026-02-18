"""Introspection endpoints — list agents, skills, tools, and trigger reload."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.errors import error_response, not_found
from agent_gateway.api.models import AgentInfo, SkillInfo, ToolInfo
from agent_gateway.api.routes.base import GatewayAPIRoute

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)

_ID_PATTERN = r"^[a-zA-Z0-9_.-]+$"


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents(request: Request) -> list[AgentInfo]:
    """List all discovered agents."""
    gw: Gateway = request.app
    ws = gw.workspace
    if ws is None:
        return []

    return [
        AgentInfo(
            id=agent.id,
            description=agent.agent_prompt[:200] if agent.agent_prompt else "",
            skills=agent.skills,
            tools=agent.tools,
            model=agent.model.name,
            schedules=[s.name for s in agent.schedules],
        )
        for agent in ws.agents.values()
    ]


@router.get("/agents/{agent_id}", response_model=AgentInfo)
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
        description=agent.agent_prompt[:200] if agent.agent_prompt else "",
        skills=agent.skills,
        tools=agent.tools,
        model=agent.model.name,
        schedules=[s.name for s in agent.schedules],
    )


@router.get("/skills", response_model=list[SkillInfo])
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
        )
        for skill in ws.skills.values()
    ]


@router.get("/skills/{skill_id}", response_model=SkillInfo)
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
    )


@router.get("/tools", response_model=list[ToolInfo])
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


@router.get("/tools/{tool_id}", response_model=ToolInfo)
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


@router.post("/reload")
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
