"""OpenTelemetry tracing helpers for Agent Gateway."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode, Tracer

from agent_gateway.telemetry import attributes as attr


def get_tracer(name: str = "agent-gateway") -> Tracer:
    """Get an OpenTelemetry tracer instance."""
    return trace.get_tracer(name)


@contextmanager
def agent_invoke_span(
    agent_id: str,
    execution_id: str,
    **extra: Any,
) -> Generator[Span, None, None]:
    """Create a root span for an agent invocation."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        attr.OP_AGENT_INVOKE,
        attributes={
            attr.GEN_AI_OPERATION_NAME: attr.OP_AGENT_INVOKE,
            attr.AGW_AGENT_ID: agent_id,
            attr.AGW_EXECUTION_ID: execution_id,
            **extra,
        },
    ) as span:
        yield span


@contextmanager
def llm_call_span(
    model: str,
    agent_id: str,
    **extra: Any,
) -> Generator[Span, None, None]:
    """Create a span for an LLM call."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        attr.OP_LLM_CALL,
        attributes={
            attr.GEN_AI_OPERATION_NAME: attr.OP_LLM_CALL,
            attr.GEN_AI_REQUEST_MODEL: model,
            attr.AGW_AGENT_ID: agent_id,
            **extra,
        },
    ) as span:
        yield span


@contextmanager
def tool_execute_span(
    tool_name: str,
    tool_type: str,
    **extra: Any,
) -> Generator[Span, None, None]:
    """Create a span for a tool execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        attr.OP_TOOL_EXECUTE,
        attributes={
            attr.GEN_AI_OPERATION_NAME: attr.OP_TOOL_EXECUTE,
            attr.AGW_TOOL_NAME: tool_name,
            attr.AGW_TOOL_TYPE: tool_type,
            **extra,
        },
    ) as span:
        yield span


@contextmanager
def output_validate_span(**extra: Any) -> Generator[Span, None, None]:
    """Create a span for output validation."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        attr.OP_OUTPUT_VALIDATE,
        attributes={
            attr.GEN_AI_OPERATION_NAME: attr.OP_OUTPUT_VALIDATE,
            **extra,
        },
    ) as span:
        yield span


@contextmanager
def queue_process_span(
    execution_id: str,
    agent_id: str,
    worker_id: int,
    **extra: Any,
) -> Generator[Span, None, None]:
    """Create a span for processing a queue job."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        attr.OP_QUEUE_PROCESS,
        attributes={
            attr.GEN_AI_OPERATION_NAME: attr.OP_QUEUE_PROCESS,
            attr.AGW_EXECUTION_ID: execution_id,
            attr.AGW_AGENT_ID: agent_id,
            attr.AGW_WORKER_ID: worker_id,
            **extra,
        },
    ) as span:
        yield span


def set_span_error(span: Span, error: Exception) -> None:
    """Record an error on a span."""
    span.set_status(StatusCode.ERROR, str(error))
    span.record_exception(error)


def set_span_ok(span: Span) -> None:
    """Mark a span as successful."""
    span.set_status(StatusCode.OK)
