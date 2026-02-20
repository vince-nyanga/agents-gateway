"""Structured exception hierarchy for Agent Gateway."""

from __future__ import annotations


class AgentGatewayError(Exception):
    """Base exception for all agent-gateway errors."""


class ConfigError(AgentGatewayError):
    """Invalid or missing configuration."""


class WorkspaceError(AgentGatewayError):
    """Error loading or parsing the workspace."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


class ExecutionError(AgentGatewayError):
    """Error during agent execution."""

    def __init__(self, message: str, execution_id: str | None = None) -> None:
        self.execution_id = execution_id
        super().__init__(message)


class ToolError(ExecutionError):
    """Error executing a tool."""

    def __init__(
        self,
        message: str,
        tool_name: str,
        execution_id: str | None = None,
    ) -> None:
        self.tool_name = tool_name
        super().__init__(message, execution_id)


class GuardrailTriggered(ExecutionError):
    """A guardrail limit was hit (max iterations, max tool calls, timeout)."""

    def __init__(
        self,
        reason: str,
        partial_result: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        self.reason = reason
        self.partial_result = partial_result
        super().__init__(f"Guardrail triggered: {reason}", execution_id)


class InputValidationError(AgentGatewayError):
    """Raised when input fails schema validation."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        self.errors = errors or []
        super().__init__(message)


class AuthError(AgentGatewayError):
    """Authentication or authorization failure."""

    def __init__(self, message: str, code: str = "auth_error") -> None:
        self.code = code
        super().__init__(message)
