"""SSE streaming support for chat executions."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import jsonschema

from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    StopReason,
    ToolCall,
    ToolContext,
    UsageAccumulator,
)
from agent_gateway.tools.runner import execute_tool

if TYPE_CHECKING:
    from agent_gateway.chat.session import ChatSession
    from agent_gateway.gateway import Gateway
    from agent_gateway.workspace.agent import AgentDefinition

logger = logging.getLogger(__name__)

MAX_RESULT_SIZE = 32 * 1024  # 32KB


def _sse_event(event_type: str, data: Any) -> str:
    """Format a Server-Sent Event."""
    json_data = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event_type}\ndata: {json_data}\n\n"


def _truncate_result(result: str) -> str:
    """Truncate tool result if it exceeds the size limit."""
    if len(result) <= MAX_RESULT_SIZE:
        return result
    return result[:MAX_RESULT_SIZE] + "\n[truncated: result exceeded 32KB limit]"


def _serialize_tool_output(output: Any) -> str:
    """Serialize tool output to string for the LLM."""
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output)
    except (TypeError, ValueError):
        return str(output)


async def stream_chat_execution(
    gw: Gateway,
    agent: AgentDefinition,
    session: ChatSession,
    messages: list[dict[str, Any]],
    exec_options: ExecutionOptions,
    execution_id: str,
    handle: ExecutionHandle,
) -> AsyncIterator[str]:
    """Stream a chat execution as SSE events.

    The session lock is acquired inside this generator so it is held for the
    full duration of streaming (not released prematurely when the route handler
    returns the StreamingResponse).

    Yields SSE-formatted strings for each event:
    - session: initial session/execution info
    - token: text content chunks
    - tool_call: tool invocation info
    - tool_result: tool execution result
    - error: error information
    - done: final status and usage
    """
    snapshot = gw._snapshot
    if snapshot is None or snapshot.engine is None:
        yield _sse_event("error", {"message": "Engine not available"})
        return

    # Acquire session lock inside the generator to hold it during streaming
    async with session.lock:
        # Emit session info
        yield _sse_event(
            "session",
            {
                "session_id": session.session_id,
                "execution_id": execution_id,
            },
        )

        usage = UsageAccumulator()
        guardrails = gw._config.guardrails if gw._config else None
        default_timeout = guardrails.timeout_ms if guardrails else 60000
        timeout_s = (exec_options.timeout_ms or default_timeout) / 1000.0
        max_iterations = guardrails.max_iterations if guardrails else 10
        max_tool_calls = guardrails.max_tool_calls if guardrails else 20
        total_tool_calls = 0
        last_text = ""
        stop_reason = StopReason.COMPLETED

        # Resolve tools via engine's public-facing helpers
        engine = snapshot.engine
        workspace = snapshot.workspace
        skill_tool_names = engine._resolve_skill_tools(agent, workspace)
        resolved_tools = engine._registry.resolve_for_agent(
            agent.id, skill_tool_names, agent.tools
        )
        tool_declarations = engine._registry.to_llm_declarations(resolved_tools)
        tool_map = {t.name: t for t in resolved_tools}

        # Resolve model params
        model, temperature, max_tokens = engine._llm.resolve_model_params(agent.model)

        # Tool context
        tool_context = ToolContext(
            execution_id=execution_id,
            agent_id=agent.id,
            metadata=session.metadata,
        )

        start = time.monotonic()

        try:
            # Acquire concurrency semaphore to respect global limits
            async with gw._execution_semaphore:
                async with asyncio.timeout(timeout_s):
                    for _iteration in range(max_iterations):
                        if handle.is_cancelled:
                            stop_reason = StopReason.CANCELLED
                            break

                        # Stream LLM response
                        accumulated_text = ""
                        pending_tool_calls: list[ToolCall] = []

                        try:
                            async for chunk in engine._llm.stream_completion(
                                messages=messages,
                                tools=tool_declarations or None,
                                model=model,
                                temperature=temperature,
                                max_tokens=max_tokens,
                            ):
                                if chunk["type"] == "token":
                                    accumulated_text += chunk["content"]
                                    yield _sse_event("token", {"content": chunk["content"]})

                                elif chunk["type"] == "tool_call":
                                    tc_args = chunk["arguments"]
                                    try:
                                        parsed_args = json.loads(tc_args) if tc_args else {}
                                    except json.JSONDecodeError:
                                        parsed_args = {"_raw": tc_args}

                                    tc = ToolCall(
                                        name=chunk["name"],
                                        arguments=parsed_args,
                                        call_id=chunk["call_id"],
                                    )
                                    pending_tool_calls.append(tc)
                                    yield _sse_event(
                                        "tool_call",
                                        {
                                            "name": tc.name,
                                            "arguments": tc.arguments,
                                            "call_id": tc.call_id,
                                        },
                                    )

                                elif chunk["type"] == "usage":
                                    usage.add_llm_usage(
                                        model=chunk.get("model", ""),
                                        input_tokens=chunk.get("input_tokens", 0),
                                        output_tokens=chunk.get("output_tokens", 0),
                                        cost=chunk.get("cost", 0.0),
                                    )

                        except Exception as e:
                            logger.error("LLM streaming failed: %s", e)
                            yield _sse_event("error", {"message": "LLM call failed"})
                            stop_reason = StopReason.ERROR
                            break

                        if accumulated_text:
                            last_text = accumulated_text

                        # No tool calls -> done
                        if not pending_tool_calls:
                            stop_reason = StopReason.COMPLETED
                            break

                        # Build assistant message for history
                        assistant_msg: dict[str, Any] = {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": tc.call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.name,
                                        "arguments": json.dumps(tc.arguments),
                                    },
                                }
                                for tc in pending_tool_calls
                            ],
                        }
                        if accumulated_text:
                            assistant_msg["content"] = accumulated_text
                        messages.append(assistant_msg)

                        # Execute tools with validation
                        for tc in pending_tool_calls:
                            if total_tool_calls >= max_tool_calls:
                                stop_reason = StopReason.MAX_TOOL_CALLS
                                break

                            resolved = tool_map.get(tc.name)
                            if resolved is None:
                                tool_output: Any = {"error": f"Unknown tool: '{tc.name}'"}
                                yield _sse_event(
                                    "tool_result",
                                    {
                                        "call_id": tc.call_id,
                                        "name": tc.name,
                                        "output": tool_output,
                                    },
                                )
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.call_id,
                                        "content": json.dumps(tool_output),
                                    }
                                )
                                total_tool_calls += 1
                                continue

                            # Permission check
                            if not resolved.allows_agent(tool_context.agent_id):
                                tool_output = {
                                    "error": (f"Tool '{tc.name}' is not permitted for this agent")
                                }
                                yield _sse_event(
                                    "tool_result",
                                    {
                                        "call_id": tc.call_id,
                                        "name": tc.name,
                                        "output": tool_output,
                                    },
                                )
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.call_id,
                                        "content": json.dumps(tool_output),
                                    }
                                )
                                total_tool_calls += 1
                                continue

                            # Validate arguments against schema
                            if resolved.parameters_schema:
                                try:
                                    jsonschema.validate(
                                        instance=tc.arguments,
                                        schema=resolved.parameters_schema,
                                    )
                                except jsonschema.ValidationError as e:
                                    tool_output = {
                                        "error": (
                                            f"Invalid arguments for tool '{tc.name}': {e.message}"
                                        )
                                    }
                                    yield _sse_event(
                                        "tool_result",
                                        {
                                            "call_id": tc.call_id,
                                            "name": tc.name,
                                            "output": tool_output,
                                        },
                                    )
                                    messages.append(
                                        {
                                            "role": "tool",
                                            "tool_call_id": tc.call_id,
                                            "content": json.dumps(tool_output),
                                        }
                                    )
                                    total_tool_calls += 1
                                    continue

                            try:
                                usage.add_tool_call()
                                result = await execute_tool(resolved, tc.arguments, tool_context)
                                output_str = _truncate_result(_serialize_tool_output(result))
                                yield _sse_event(
                                    "tool_result",
                                    {
                                        "call_id": tc.call_id,
                                        "name": tc.name,
                                        "output": result,
                                    },
                                )
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.call_id,
                                        "content": output_str,
                                    }
                                )
                            except Exception as e:
                                logger.error(
                                    "Tool '%s' failed during streaming: %s",
                                    tc.name,
                                    e,
                                )
                                tool_error = {"error": f"Tool '{tc.name}' failed"}
                                yield _sse_event(
                                    "tool_result",
                                    {
                                        "call_id": tc.call_id,
                                        "name": tc.name,
                                        "output": tool_error,
                                    },
                                )
                                messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.call_id,
                                        "content": json.dumps(tool_error),
                                    }
                                )

                            total_tool_calls += 1

                        if total_tool_calls >= max_tool_calls:
                            stop_reason = StopReason.MAX_TOOL_CALLS
                            break
                    else:
                        stop_reason = StopReason.MAX_ITERATIONS

        except TimeoutError:
            stop_reason = StopReason.TIMEOUT
            yield _sse_event("error", {"message": "Execution timed out"})
        except asyncio.CancelledError:
            stop_reason = StopReason.CANCELLED

        # Update session with final assistant message
        if last_text:
            session.append_assistant_message(content=last_text)

        duration_ms = int((time.monotonic() - start) * 1000)

        # Emit done event
        yield _sse_event(
            "done",
            {
                "status": stop_reason.value,
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cost_usd": round(usage.cost_usd, 6),
                    "llm_calls": usage.llm_calls,
                    "tool_calls": usage.tool_calls,
                    "models_used": list(usage.models_used),
                    "duration_ms": duration_ms,
                },
                "turn_count": session.turn_count,
            },
        )
