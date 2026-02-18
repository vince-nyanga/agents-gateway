"""Introspection endpoints — list agents, skills, tools, and trigger reload."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.models import (
    AgentInfo,
    ErrorDetail,
    ErrorResponse,
    SkillInfo,
    ToolInfo,
)
from agent_gateway.api.routes.base import GatewayAPIRoute

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents(request: Request) -> list[AgentInfo]:
    """List all discovered agents."""
    gw: Gateway = request.app  # type: ignore[assignment]
    if gw._workspace is None:
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
        for agent in gw._workspace.agents.values()
    ]


@router.get("/agents/{agent_id}", response_model=AgentInfo)
async def get_agent(agent_id: str, request: Request) -> AgentInfo | JSONResponse:
    """Get details of a specific agent."""
    gw: Gateway = request.app  # type: ignore[assignment]
    if gw._workspace is None:
        return _not_found("agent", agent_id)

    agent = gw._workspace.agents.get(agent_id)
    if agent is None:
        return _not_found("agent", agent_id)

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
    gw: Gateway = request.app  # type: ignore[assignment]
    if gw._workspace is None:
        return []

    return [
        SkillInfo(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            tools=skill.tools,
        )
        for skill in gw._workspace.skills.values()
    ]


@router.get("/skills/{skill_id}", response_model=SkillInfo)
async def get_skill(skill_id: str, request: Request) -> SkillInfo | JSONResponse:
    """Get details of a specific skill."""
    gw: Gateway = request.app  # type: ignore[assignment]
    if gw._workspace is None:
        return _not_found("skill", skill_id)

    skill = gw._workspace.skills.get(skill_id)
    if skill is None:
        return _not_found("skill", skill_id)

    return SkillInfo(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        tools=skill.tools,
    )


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools(request: Request) -> list[ToolInfo]:
    """List all registered tools (file-based + code-based)."""
    gw: Gateway = request.app  # type: ignore[assignment]
    if gw._tool_registry is None:
        return []

    return [
        ToolInfo(
            id=tool.name,
            name=tool.name,
            description=tool.description,
            source=tool.source,
            parameters=tool.parameters_schema,
        )
        for tool in gw._tool_registry.get_all().values()
    ]


@router.get("/tools/{tool_id}", response_model=ToolInfo)
async def get_tool(tool_id: str, request: Request) -> ToolInfo | JSONResponse:
    """Get details of a specific tool."""
    gw: Gateway = request.app  # type: ignore[assignment]
    if gw._tool_registry is None:
        return _not_found("tool", tool_id)

    tool = gw._tool_registry.get(tool_id)
    if tool is None:
        return _not_found("tool", tool_id)

    return ToolInfo(
        id=tool.name,
        name=tool.name,
        description=tool.description,
        source=tool.source,
        parameters=tool.parameters_schema,
    )


@router.post("/reload")
async def reload_workspace(request: Request) -> JSONResponse:
    """Re-scan workspace and reload all definitions."""
    gw: Gateway = request.app  # type: ignore[assignment]

    try:
        await gw._reload_workspace()
        workspace = gw._workspace
        agent_count = len(workspace.agents) if workspace else 0
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "agents": agent_count,
                "message": "Workspace reloaded successfully",
            },
        )
    except Exception as e:
        logger.error("Workspace reload failed: %s", e)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="reload_failed",
                    message=f"Workspace reload failed: {e}",
                )
            ).model_dump(),
        )


def _not_found(resource_type: str, resource_id: str) -> JSONResponse:
    """Standard 404 response."""
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error=ErrorDetail(
                code=f"{resource_type}_not_found",
                message=f"{resource_type.title()} '{resource_id}' not found",
            )
        ).model_dump(),
    )
