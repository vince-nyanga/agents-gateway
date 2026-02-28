"""Admin CRUD endpoints for MCP server configurations."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from agent_gateway.api.errors import error_response, not_found
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.auth.scopes import RequireScope
from agent_gateway.persistence.domain import McpServerConfig

logger = logging.getLogger(__name__)

router = APIRouter(route_class=GatewayAPIRoute)

_VALID_AUTH_TYPES = {
    "none",
    "static_header",
    "google_service_account",
    "oauth2_client_credentials",
}


def _validate_auth_credentials(credentials: dict[str, Any] | None) -> None:
    """Validate OAuth2 credential shapes. Shared by Create and Update models."""
    if not credentials or "auth_type" not in credentials:
        return
    at = credentials["auth_type"]
    if at not in _VALID_AUTH_TYPES:
        raise ValueError(f"Unknown auth_type '{at}'. Must be one of: {sorted(_VALID_AUTH_TYPES)}")
    if at == "google_service_account":
        for key in ("service_account_json", "scopes"):
            if key not in credentials:
                raise ValueError(
                    f"credentials must contain '{key}' for auth_type 'google_service_account'"
                )
    elif at == "oauth2_client_credentials":
        for key in ("token_url", "client_id", "client_secret"):
            if key not in credentials:
                raise ValueError(
                    f"credentials must contain '{key}' for auth_type 'oauth2_client_credentials'"
                )


class CreateMcpServerRequest(BaseModel):
    name: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)
    transport: Literal["stdio", "streamable_http"]
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None  # plaintext, encrypted before storage
    url: str | None = None
    headers: dict[str, str] | None = None
    credentials: dict[str, Any] | None = None  # plaintext, encrypted before storage
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> CreateMcpServerRequest:
        if self.transport == "stdio" and not self.command:
            raise ValueError("'command' is required for stdio transport")
        if self.transport == "streamable_http" and not self.url:
            raise ValueError("'url' is required for streamable_http transport")
        if self.transport == "stdio" and self.url:
            raise ValueError("'url' should not be set for stdio transport")
        if self.transport == "streamable_http" and self.command:
            raise ValueError("'command' should not be set for streamable_http transport")
        _validate_auth_credentials(self.credentials)
        return self


class UpdateMcpServerRequest(BaseModel):
    """Update an MCP server config. All fields are optional.

    Semantics:
    - Present field with a value: replaces the existing value.
    - Absent field (not in JSON body): left unchanged.
    - credentials/env: if provided, fully replaces the encrypted blob.
      To clear credentials, send an empty dict {}.
    """

    name: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)
    transport: Literal["stdio", "streamable_http"] | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    credentials: dict[str, Any] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> UpdateMcpServerRequest:
        if self.transport == "stdio" and self.url is not None:
            raise ValueError("'url' should not be set for stdio transport")
        if self.transport == "streamable_http" and self.command is not None:
            raise ValueError("'command' should not be set for streamable_http transport")
        _validate_auth_credentials(self.credentials)
        return self


class McpServerResponse(BaseModel):
    id: str
    name: str
    transport: str
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    header_keys: list[str] = Field(default_factory=list)  # header names only, never values
    enabled: bool
    credential_keys: list[str]  # names only, never values
    has_env: bool  # whether encrypted env is set
    auth_type: str  # "none", "static_header", "google_service_account", etc.
    tool_count: int
    connected: bool
    created_at: str
    updated_at: str | None = None


class McpTestToolResponse(BaseModel):
    name: str
    description: str


class McpTestResponse(BaseModel):
    success: bool
    tool_count: int
    tools: list[McpTestToolResponse]
    error: str | None = None
    error_code: str | None = None


class McpToolResponse(BaseModel):
    name: str  # namespaced: "server__tool"
    original_name: str  # MCP-native name
    server_name: str
    description: str
    input_schema: dict[str, Any]


@router.post(
    "/admin/mcp-servers",
    response_model=McpServerResponse,
    summary="Create MCP server config",
    tags=["Admin"],
    dependencies=[Depends(RequireScope("admin:*"))],
)
async def create_mcp_server(request: Request, body: CreateMcpServerRequest) -> McpServerResponse:
    gw = request.app
    from agent_gateway.secrets import encrypt_value

    encrypted_creds = encrypt_value(json.dumps(body.credentials)) if body.credentials else None
    encrypted_env = encrypt_value(json.dumps(body.env)) if body.env else None
    encrypted_hdrs = encrypt_value(json.dumps(body.headers)) if body.headers else None

    config = McpServerConfig(
        id=str(uuid.uuid4()),
        name=body.name,
        transport=body.transport,
        command=body.command,
        args=body.args,
        encrypted_env=encrypted_env,
        url=body.url,
        encrypted_headers=encrypted_hdrs,
        encrypted_credentials=encrypted_creds,
        enabled=body.enabled,
        created_at=datetime.now(UTC),
    )

    await gw._mcp_repo.upsert(config)

    # Audit log
    await gw._audit_repo.log(
        event_type="mcp_server.created",
        actor=_get_actor(request),
        resource_type="mcp_server",
        resource_id=config.id,
        metadata={"name": config.name, "transport": config.transport},
    )

    return _to_response(config, gw._mcp_manager)


@router.get(
    "/admin/mcp-servers",
    response_model=list[McpServerResponse],
    summary="List MCP server configs",
    tags=["Admin"],
    dependencies=[Depends(RequireScope("admin:*"))],
)
async def list_mcp_servers(request: Request) -> list[McpServerResponse]:
    gw = request.app
    configs = await gw._mcp_repo.list_all()
    return [_to_response(c, gw._mcp_manager) for c in configs]


@router.get(
    "/admin/mcp-servers/{server_id}",
    response_model=McpServerResponse,
    summary="Get MCP server config",
    tags=["Admin"],
    dependencies=[Depends(RequireScope("admin:*"))],
)
async def get_mcp_server(request: Request, server_id: str = Path(...)) -> Any:
    gw = request.app
    config = await gw._mcp_repo.get_by_id(server_id)
    if config is None:
        return not_found("mcp_server", server_id)
    return _to_response(config, gw._mcp_manager)


@router.put(
    "/admin/mcp-servers/{server_id}",
    response_model=McpServerResponse,
    summary="Update MCP server config",
    tags=["Admin"],
    dependencies=[Depends(RequireScope("admin:*"))],
)
async def update_mcp_server(
    request: Request,
    body: UpdateMcpServerRequest,
    server_id: str = Path(...),
) -> Any:
    gw = request.app
    from agent_gateway.secrets import encrypt_value

    existing = await gw._mcp_repo.get_by_id(server_id)
    if existing is None:
        return not_found("mcp_server", server_id)

    update_data = body.model_dump(exclude_unset=True)

    if "name" in update_data:
        existing.name = update_data["name"]
    if "transport" in update_data:
        existing.transport = update_data["transport"]
    if "command" in update_data:
        existing.command = update_data["command"]
    if "args" in update_data:
        existing.args = update_data["args"]
    if "url" in update_data:
        existing.url = update_data["url"]
    if "headers" in update_data:
        existing.encrypted_headers = (
            encrypt_value(json.dumps(update_data["headers"])) if update_data["headers"] else None
        )
    if "enabled" in update_data:
        existing.enabled = update_data["enabled"]
    if "credentials" in update_data:
        existing.encrypted_credentials = (
            encrypt_value(json.dumps(update_data["credentials"]))
            if update_data["credentials"]
            else None
        )
    if "env" in update_data:
        existing.encrypted_env = (
            encrypt_value(json.dumps(update_data["env"])) if update_data["env"] else None
        )
    existing.updated_at = datetime.now(UTC)

    await gw._mcp_repo.upsert(existing)

    # Audit log
    await gw._audit_repo.log(
        event_type="mcp_server.updated",
        actor=_get_actor(request),
        resource_type="mcp_server",
        resource_id=existing.id,
        metadata={"name": existing.name, "fields_updated": list(update_data.keys())},
    )

    return _to_response(existing, gw._mcp_manager)


@router.delete(
    "/admin/mcp-servers/{server_id}",
    summary="Delete MCP server config",
    tags=["Admin"],
    dependencies=[Depends(RequireScope("admin:*"))],
)
async def delete_mcp_server(request: Request, server_id: str = Path(...)) -> JSONResponse:
    gw = request.app
    existing = await gw._mcp_repo.get_by_id(server_id)
    if existing is None:
        return not_found("mcp_server", server_id)

    # Disconnect if connected
    if gw._mcp_manager is not None:
        await gw._mcp_manager.disconnect_one(existing.name)

    deleted = await gw._mcp_repo.delete(server_id)

    # Audit log
    await gw._audit_repo.log(
        event_type="mcp_server.deleted",
        actor=_get_actor(request),
        resource_type="mcp_server",
        resource_id=server_id,
        metadata={"name": existing.name},
    )

    return JSONResponse({"deleted": deleted})


@router.post(
    "/admin/mcp-servers/{server_id}/refresh",
    response_model=McpServerResponse,
    summary="Reconnect and rediscover tools",
    tags=["Admin"],
    dependencies=[Depends(RequireScope("admin:*"))],
)
async def refresh_mcp_server(request: Request, server_id: str = Path(...)) -> Any:
    gw = request.app
    config = await gw._mcp_repo.get_by_id(server_id)
    if config is None:
        return not_found("mcp_server", server_id)

    if gw._mcp_manager is None:
        return error_response(503, "mcp_unavailable", "MCP manager not initialized")

    await gw._mcp_manager.refresh_server(config.name, config)

    # Re-register tools for this specific server only
    _reregister_mcp_tools(gw, server_name=config.name)

    return _to_response(config, gw._mcp_manager)


@router.post(
    "/admin/mcp-servers/{server_id}/test",
    response_model=McpTestResponse,
    summary="Test MCP server connection",
    tags=["Admin"],
    dependencies=[Depends(RequireScope("admin:*"))],
)
async def test_mcp_server(request: Request, server_id: str = Path(...)) -> Any:
    """Temporarily connect to an MCP server, list tools, and disconnect."""
    gw = request.app
    config = await gw._mcp_repo.get_by_id(server_id)
    if config is None:
        return not_found("mcp_server", server_id)

    if gw._mcp_manager is None:
        return McpTestResponse(
            success=False,
            tool_count=0,
            tools=[],
            error="MCP manager not initialized",
            error_code="config_error",
        )

    try:
        result = await gw._mcp_manager.test_connection(config)
        return McpTestResponse(
            success=True,
            tool_count=result["tool_count"],
            tools=[McpTestToolResponse(**t) for t in result["tools"]],
        )
    except Exception as exc:
        from agent_gateway.exceptions import McpAuthError, McpConnectionError

        error_code = "connection_error"
        if isinstance(exc, McpAuthError):
            error_code = "auth_error"
        elif isinstance(exc, McpConnectionError) and "timed out" in str(exc):
            error_code = "timeout"
        elif isinstance(exc, (ValueError, TypeError)):
            error_code = "config_error"

        return McpTestResponse(
            success=False,
            tool_count=0,
            tools=[],
            error=str(exc),
            error_code=error_code,
        )


@router.get(
    "/admin/mcp-servers/{server_id}/tools",
    response_model=list[McpToolResponse],
    summary="List discovered tools for an MCP server",
    tags=["Admin"],
    dependencies=[Depends(RequireScope("admin:*"))],
)
async def list_mcp_server_tools(request: Request, server_id: str = Path(...)) -> Any:
    gw = request.app
    config = await gw._mcp_repo.get_by_id(server_id)
    if config is None:
        return not_found("mcp_server", server_id)

    if gw._mcp_manager is None:
        return []

    tools = gw._mcp_manager.get_tools(config.name)
    return [
        McpToolResponse(
            name=t.namespaced_name,
            original_name=t.name,
            server_name=t.server_name,
            description=t.description,
            input_schema=t.input_schema,
        )
        for t in tools
    ]


# --- Helpers ---


def _get_actor(request: Request) -> str:
    """Extract actor identity from request for audit logging."""
    identity = getattr(request.state, "identity", None)
    return str(identity) if identity else "unknown"


def _to_response(config: McpServerConfig, manager: Any) -> McpServerResponse:
    """Convert domain object to API response (never exposing secrets)."""
    from agent_gateway.secrets import decrypt_json_blob

    # Decrypt headers to get key names only
    header_keys: list[str] = []
    if config.encrypted_headers:
        try:
            decrypted_headers = decrypt_json_blob(config.encrypted_headers)
            header_keys = list(decrypted_headers.keys())
        except Exception:
            header_keys = ["<decryption_failed>"]

    # Decrypt credentials once -- reuse for both cred_keys and auth_type
    creds: dict[str, Any] = {}
    cred_keys: list[str] = []
    if config.encrypted_credentials:
        try:
            creds = decrypt_json_blob(config.encrypted_credentials)
            cred_keys = list(creds.keys())
        except Exception:
            cred_keys = ["<decryption_failed>"]

    # Determine auth type from decrypted credentials
    auth_type = "none"
    if creds:
        auth_type = creds.get("auth_type", "static_header")

    tool_count = 0
    connected = False
    if manager is not None:
        tool_count = len(manager.get_tools(config.name))
        connected = manager.is_connected(config.name)

    return McpServerResponse(
        id=config.id,
        name=config.name,
        transport=config.transport,
        command=config.command,
        args=config.args,
        url=config.url,
        header_keys=header_keys,
        enabled=config.enabled,
        credential_keys=cred_keys,
        has_env=bool(config.encrypted_env),
        auth_type=auth_type,
        tool_count=tool_count,
        connected=connected,
        created_at=config.created_at.isoformat() if config.created_at else "",
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


def _reregister_mcp_tools(gw: Any, server_name: str | None = None) -> None:
    """Recompute allowed_agents and re-register MCP tools.

    Args:
        gw: Gateway instance.
        server_name: If provided, only refresh tools for this server.
            If None, refreshes all MCP tools.
    """
    from agent_gateway.mcp.manager import compute_server_to_agents

    if gw._snapshot is None:
        logger.warning("Cannot re-register MCP tools: gateway snapshot not initialized")
        return

    gw._snapshot.tool_registry.clear_mcp_tools(server_name=server_name)

    server_to_agents = compute_server_to_agents(gw._snapshot.workspace)

    if server_name is not None:
        # Only re-register tools for the specific server
        tools = gw._mcp_manager.get_tools(server_name)
        if tools:
            allowed = server_to_agents.get(server_name)
            gw._snapshot.tool_registry.register_mcp_tools(tools, allowed_agents=allowed)
    else:
        all_mcp_tools = gw._mcp_manager.get_all_tools()
        for sname, tools in all_mcp_tools.items():
            allowed = server_to_agents.get(sname)
            gw._snapshot.tool_registry.register_mcp_tools(tools, allowed_agents=allowed)
