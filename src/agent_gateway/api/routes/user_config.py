"""Per-user agent configuration CRUD endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse

from agent_gateway.api.errors import error_response
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.auth.scopes import RequireScope

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)


def _get_user_id(request: Request, gw: Gateway) -> str | None:
    """Extract user_id from auth context."""
    auth = request.scope.get("auth")
    return gw._derive_user_id(auth) if auth else None


@router.get(
    "/agents/{agent_id}/setup-schema",
    dependencies=[Depends(RequireScope("agents:read"))],
)
async def get_setup_schema(
    request: Request,
    agent_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> JSONResponse:
    """Get the setup schema for a personal agent."""
    gw: Gateway = request.app

    snapshot = gw._snapshot
    if snapshot is None or snapshot.workspace is None:
        return error_response(503, "workspace_unavailable", "Workspace not loaded")

    agent = snapshot.workspace.agents.get(agent_id)
    if agent is None:
        return error_response(404, "agent_not_found", f"Agent '{agent_id}' not found")

    if agent.scope != "personal":
        return error_response(
            400, "not_personal_agent", f"Agent '{agent_id}' is not a personal agent"
        )

    return JSONResponse(
        status_code=200,
        content={
            "agent_id": agent_id,
            "scope": agent.scope,
            "setup_schema": agent.setup_schema,
        },
    )


@router.post(
    "/agents/{agent_id}/config",
    dependencies=[Depends(RequireScope("agents:configure"))],
)
async def save_user_config(
    request: Request,
    body: dict[str, Any],
    agent_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> JSONResponse:
    """Save user's configuration for a personal agent."""
    gw: Gateway = request.app

    user_id = _get_user_id(request, gw)
    if user_id is None:
        return error_response(401, "auth_required", "Authentication required")

    snapshot = gw._snapshot
    if snapshot is None or snapshot.workspace is None:
        return error_response(503, "workspace_unavailable", "Workspace not loaded")

    agent = snapshot.workspace.agents.get(agent_id)
    if agent is None:
        return error_response(404, "agent_not_found", f"Agent '{agent_id}' not found")

    if agent.scope != "personal":
        return error_response(
            400, "not_personal_agent", f"Agent '{agent_id}' is not a personal agent"
        )

    # Validate against setup_schema if present
    if agent.setup_schema:
        import jsonschema

        # Extract only the config values (not instructions)
        config_input = {k: v for k, v in body.items() if k not in ("instructions",)}
        try:
            jsonschema.validate(instance=config_input, schema=agent.setup_schema)
        except jsonschema.ValidationError as e:
            return error_response(
                422, "validation_failed", f"Config validation failed: {e.message}"
            )

    # Separate instructions, sensitive fields, and regular config
    instructions = body.get("instructions")
    config_values: dict[str, Any] = {}
    encrypted_secrets: dict[str, Any] = {}

    from agent_gateway.secrets import encrypt_value, get_sensitive_fields

    sensitive_fields = get_sensitive_fields(agent.setup_schema) if agent.setup_schema else set()

    for key, value in body.items():
        if key == "instructions":
            continue
        if key in sensitive_fields and isinstance(value, str):
            encrypted_secrets[key] = encrypt_value(value)
        else:
            config_values[key] = value

    # Determine if setup is complete (all required fields provided)
    setup_completed = True
    if agent.setup_schema:
        required = set(agent.setup_schema.get("required", []))
        provided = set(config_values.keys()) | set(encrypted_secrets.keys())
        setup_completed = required.issubset(provided)

    from agent_gateway.persistence.domain import UserAgentConfig

    now = datetime.now(UTC)
    config = UserAgentConfig(
        user_id=user_id,
        agent_id=agent_id,
        instructions=instructions,
        config_values=config_values,
        encrypted_secrets=encrypted_secrets,
        setup_completed=setup_completed,
        created_at=now,
        updated_at=now,
    )
    await gw._user_agent_config_repo.upsert(config)

    return JSONResponse(
        status_code=200,
        content={
            "user_id": user_id,
            "agent_id": agent_id,
            "setup_completed": setup_completed,
        },
    )


@router.get(
    "/agents/{agent_id}/config",
    dependencies=[Depends(RequireScope("agents:configure"))],
)
async def get_user_config(
    request: Request,
    agent_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> JSONResponse:
    """Get user's config for an agent (secrets redacted)."""
    gw: Gateway = request.app

    user_id = _get_user_id(request, gw)
    if user_id is None:
        return error_response(401, "auth_required", "Authentication required")

    config = await gw._user_agent_config_repo.get(user_id, agent_id)
    if config is None:
        return error_response(404, "config_not_found", "No configuration found for this agent")

    # Redact secrets
    redacted_secrets = {k: "***" for k in config.encrypted_secrets}

    return JSONResponse(
        status_code=200,
        content={
            "user_id": config.user_id,
            "agent_id": config.agent_id,
            "instructions": config.instructions,
            "config_values": config.config_values,
            "secrets": redacted_secrets,
            "setup_completed": config.setup_completed,
            "created_at": config.created_at.isoformat() if config.created_at else None,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        },
    )


@router.delete(
    "/agents/{agent_id}/config",
    dependencies=[Depends(RequireScope("agents:configure"))],
)
async def delete_user_config(
    request: Request,
    agent_id: str = Path(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"),
) -> JSONResponse:
    """Delete user's config for an agent."""
    gw: Gateway = request.app

    user_id = _get_user_id(request, gw)
    if user_id is None:
        return error_response(401, "auth_required", "Authentication required")

    deleted = await gw._user_agent_config_repo.delete(user_id, agent_id)
    if not deleted:
        return error_response(404, "config_not_found", "No configuration found for this agent")

    return JSONResponse(status_code=200, content={"deleted": True})
