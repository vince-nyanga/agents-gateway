"""Pydantic models for API request/response."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_gateway.engine.models import ExecutionStatus


class InvokeOptions(BaseModel):
    """Options for an agent invocation.

    The ``async_`` field uses ``alias="async"`` so callers can send
    ``{"async": true}`` in JSON.  ``populate_by_name`` allows either form.
    """

    async_: bool = Field(False, alias="async")
    timeout_ms: int | None = Field(None, ge=1000, le=300_000)

    model_config = {"populate_by_name": True}


class InvokeRequest(BaseModel):
    """Request body for POST /v1/agents/{agent_id}/invoke."""

    message: str = Field(..., max_length=102_400)
    context: dict[str, Any] = Field(default_factory=dict)
    options: InvokeOptions = Field(default_factory=InvokeOptions)


class UsagePayload(BaseModel):
    """Token usage and cost information."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    models_used: list[str] = Field(default_factory=list)
    duration_ms: int = 0


class ResultPayload(BaseModel):
    """Execution result payload."""

    output: Any = None
    raw_text: str = ""
    validation_errors: list[str] | None = None


class InvokeResponse(BaseModel):
    """Response body for POST /v1/agents/{agent_id}/invoke."""

    execution_id: str
    agent_id: str
    status: ExecutionStatus
    result: ResultPayload | None = None
    usage: UsagePayload | None = None
    error: str | None = None


class ErrorDetail(BaseModel):
    """Structured error information."""

    code: str
    message: str
    execution_id: str | None = None


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: ErrorDetail


class ExecutionResponse(BaseModel):
    """Response for GET /v1/executions/{execution_id}."""

    execution_id: str
    agent_id: str
    status: ExecutionStatus
    message: str
    context: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


class AgentInfo(BaseModel):
    """Agent summary for introspection."""

    id: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    model: str | None = None
    schedules: list[str] = Field(default_factory=list)


class SkillInfo(BaseModel):
    """Skill summary for introspection."""

    id: str
    name: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)


class ToolInfo(BaseModel):
    """Tool summary for introspection."""

    name: str
    description: str = ""
    source: Literal["file", "code", ""] = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Response for GET /v1/health."""

    status: Literal["ok", "degraded"]
    agent_count: int = 0
    skill_count: int = 0
    tool_count: int = 0
