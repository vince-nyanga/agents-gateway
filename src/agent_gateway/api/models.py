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

    async_: bool = Field(
        False,
        alias="async",
        description="Run asynchronously. Returns 202 with a poll URL.",
    )
    stream: bool = Field(False, description="Enable Server-Sent Events streaming.")
    timeout_ms: int | None = Field(
        None,
        ge=1000,
        le=300_000,
        description="Execution timeout in milliseconds (1000–300000).",
    )
    output_schema: dict[str, Any] | None = Field(
        None, description="JSON Schema for structured output validation."
    )

    model_config = {"populate_by_name": True}


class InvokeRequest(BaseModel):
    """Request body for POST /v1/agents/{agent_id}/invoke."""

    message: str = Field(..., max_length=102_400, description="The message to send to the agent.")
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value input variables for the agent.",
    )
    options: InvokeOptions = Field(
        default_factory=InvokeOptions, description="Invocation options."
    )


class UsagePayload(BaseModel):
    """Token usage and cost information."""

    input_tokens: int = Field(0, description="Total input tokens consumed.")
    output_tokens: int = Field(0, description="Total output tokens generated.")
    cost_usd: float = Field(0.0, description="Estimated cost in USD.")
    llm_calls: int = Field(0, description="Number of LLM API calls made.")
    tool_calls: int = Field(0, description="Number of tool invocations.")
    models_used: list[str] = Field(default_factory=list, description="LLM model identifiers used.")
    duration_ms: int = Field(0, description="Wall-clock duration in milliseconds.")


class ResultPayload(BaseModel):
    """Execution result payload."""

    output: Any = Field(None, description="Structured output (if output_schema was set).")
    raw_text: str = Field("", description="Raw text response from the agent.")
    validation_errors: list[str] | None = Field(
        None, description="Output schema validation errors, if any."
    )


class InvokeResponse(BaseModel):
    """Response body for POST /v1/agents/{agent_id}/invoke."""

    execution_id: str = Field(..., description="Unique execution identifier.")
    agent_id: str = Field(..., description="Agent that handled the invocation.")
    status: ExecutionStatus = Field(..., description="Current execution status.")
    result: ResultPayload | None = Field(None, description="Execution result payload.")
    usage: UsagePayload | None = Field(None, description="Token usage and cost breakdown.")
    error: str | None = Field(None, description="Error message if execution failed.")


class ErrorDetail(BaseModel):
    """Structured error information."""

    code: str = Field(..., description="Machine-readable error code.")
    message: str = Field(..., description="Human-readable error message.")
    execution_id: str | None = Field(None, description="Related execution ID, if applicable.")


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: ErrorDetail = Field(..., description="Error details.")


class ExecutionResponse(BaseModel):
    """Response for GET /v1/executions/{execution_id}."""

    execution_id: str = Field(..., description="Unique execution identifier.")
    agent_id: str = Field(..., description="Agent that handled the execution.")
    status: ExecutionStatus = Field(..., description="Current execution status.")
    message: str = Field(..., description="Original message sent to the agent.")
    input: dict[str, Any] | None = Field(None, description="Input variables provided.")
    result: dict[str, Any] | None = Field(None, description="Execution result data.")
    error: str | None = Field(None, description="Error message if execution failed.")
    usage: dict[str, Any] | None = Field(None, description="Token usage and cost data.")
    session_id: str | None = Field(None, description="Chat session ID, if applicable.")
    parent_execution_id: str | None = Field(
        None, description="Parent execution ID in a delegation chain."
    )
    root_execution_id: str | None = Field(
        None, description="Root execution ID of the delegation tree."
    )
    delegation_depth: int = Field(0, description="Depth in the delegation chain.")
    started_at: datetime | None = Field(None, description="When execution started.")
    completed_at: datetime | None = Field(None, description="When execution completed.")
    created_at: datetime | None = Field(None, description="When the record was created.")


class NotificationTargetInfo(BaseModel):
    """Notification target summary for introspection."""

    channel: str = Field(..., description="Notification channel type (slack, webhook, etc.).")
    target: str = Field("", description="Channel-specific target (e.g. Slack channel name).")


class NotificationConfigInfo(BaseModel):
    """Agent notification configuration summary."""

    on_complete: list[NotificationTargetInfo] = Field(
        default_factory=list, description="Targets notified on successful completion."
    )
    on_error: list[NotificationTargetInfo] = Field(
        default_factory=list, description="Targets notified on error."
    )
    on_timeout: list[NotificationTargetInfo] = Field(
        default_factory=list, description="Targets notified on timeout."
    )


class AgentInfo(BaseModel):
    """Agent summary for introspection."""

    id: str = Field(..., description="Unique agent identifier.")
    description: str = Field("", description="Human-readable agent description.")
    display_name: str | None = Field(None, description="Optional display name.")
    tags: list[str] = Field(default_factory=list, description="Agent tags for filtering.")
    version: str | None = Field(None, description="Agent version string.")
    skills: list[str] = Field(default_factory=list, description="Skill IDs available to agent.")
    tools: list[str] = Field(default_factory=list, description="Tool names available to agent.")
    model: str | None = Field(None, description="LLM model identifier.")
    schedules: list[str] = Field(
        default_factory=list, description="Cron schedule names attached to agent."
    )
    execution_mode: str = Field("sync", description="Default execution mode (sync or async).")
    notifications: NotificationConfigInfo | None = Field(
        None, description="Notification configuration."
    )
    input_schema: dict[str, Any] | None = Field(
        None, description="JSON Schema for agent input validation."
    )
    retrievers: list[str] = Field(
        default_factory=list, description="Context retriever IDs used by agent."
    )
    context_file_count: int = Field(0, description="Number of static context files attached.")
    memory_enabled: bool = Field(False, description="Whether agent memory is enabled.")


class SkillInfo(BaseModel):
    """Skill summary for introspection."""

    id: str = Field(..., description="Unique skill identifier.")
    name: str = Field(..., description="Skill display name.")
    description: str = Field("", description="Human-readable skill description.")
    tools: list[str] = Field(default_factory=list, description="Tool names used by skill.")
    has_workflow: bool = Field(False, description="Whether skill defines a multi-step workflow.")
    step_count: int = Field(0, description="Number of workflow steps.")


class ToolInfo(BaseModel):
    """Tool summary for introspection."""

    name: str = Field(..., description="Tool name.")
    description: str = Field("", description="Human-readable tool description.")
    source: Literal["file", "code", ""] = Field(
        "", description="Tool source type (file-based or code-registered)."
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema of tool parameters."
    )


class HealthResponse(BaseModel):
    """Response for GET /v1/health."""

    status: Literal["ok", "degraded"] = Field(..., description="Gateway health status.")
    agent_count: int = Field(0, description="Number of loaded agents.")
    skill_count: int = Field(0, description="Number of loaded skills.")
    tool_count: int = Field(0, description="Number of registered tools.")


# --- Chat endpoint models ---


class ChatOptions(BaseModel):
    """Options for a chat message."""

    stream: bool = Field(False, description="Enable Server-Sent Events streaming.")
    timeout_ms: int | None = Field(
        None,
        ge=1000,
        le=300_000,
        description="Execution timeout in milliseconds (1000–300000).",
    )


class ChatRequest(BaseModel):
    """Request body for POST /v1/agents/{agent_id}/chat."""

    message: str = Field(..., max_length=102_400, description="The message to send to the agent.")
    session_id: str | None = Field(
        None, description="Existing session ID to continue, or null for a new session."
    )
    input: dict[str, Any] = Field(default_factory=dict, description="Key-value input variables.")
    options: ChatOptions = Field(default_factory=ChatOptions, description="Chat options.")


class ChatResponse(BaseModel):
    """Response body for POST /v1/agents/{agent_id}/chat (non-streaming)."""

    session_id: str = Field(..., description="Session ID for this conversation.")
    execution_id: str = Field(..., description="Unique execution identifier.")
    agent_id: str = Field(..., description="Agent that handled the message.")
    status: ExecutionStatus = Field(..., description="Execution status.")
    result: ResultPayload | None = Field(None, description="Execution result payload.")
    usage: UsagePayload | None = Field(None, description="Token usage and cost breakdown.")
    error: str | None = Field(None, description="Error message if execution failed.")
    turn_count: int = Field(0, description="Number of turns in this session.")


class SessionInfo(BaseModel):
    """Session summary for introspection."""

    session_id: str = Field(..., description="Unique session identifier.")
    agent_id: str = Field(..., description="Agent associated with this session.")
    turn_count: int = Field(0, description="Number of conversation turns.")
    message_count: int = Field(0, description="Total messages in the session.")
    created_at: float = Field(0.0, description="Session creation time (Unix epoch seconds).")
    updated_at: float = Field(0.0, description="Last update time (Unix epoch seconds).")


# --- Schedule endpoint models ---


class ScheduleInfo(BaseModel):
    """Schedule summary for list endpoint."""

    id: str = Field(..., description="Unique schedule identifier.")
    agent_id: str = Field(..., description="Agent this schedule triggers.")
    name: str = Field(..., description="Human-readable schedule name.")
    cron_expr: str = Field(..., description="Cron expression (e.g. '0 9 * * 1-5').")
    enabled: bool = Field(True, description="Whether the schedule is active.")
    timezone: str = Field("UTC", description="IANA timezone for cron evaluation.")
    next_run_at: datetime | None = Field(None, description="Next scheduled execution time.")
    last_run_at: datetime | None = Field(None, description="Most recent execution time.")
    created_at: datetime | None = Field(None, description="When the schedule was created.")


class ScheduleDetailInfo(ScheduleInfo):
    """Schedule detail with message and input."""

    message: str = Field("", description="Message sent to the agent on each trigger.")
    input: dict[str, Any] = Field(
        default_factory=dict, description="Input variables for scheduled invocations."
    )
