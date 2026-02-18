"""Execution engine — the core LLM function-calling loop."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import jsonschema

from agent_gateway.config import GatewayConfig
from agent_gateway.engine.llm import LLMClient
from agent_gateway.engine.models import (
    ExecutionHandle,
    ExecutionOptions,
    ExecutionResult,
    StopReason,
    ToolCall,
    ToolContext,
    ToolResult,
    UsageAccumulator,
)
from agent_gateway.engine.output import (
    build_correction_message,
    build_schema_instruction,
    validate_output,
)
from agent_gateway.workspace.agent import AgentDefinition
from agent_gateway.workspace.loader import WorkspaceState
from agent_gateway.workspace.prompt import assemble_system_prompt
from agent_gateway.workspace.registry import ResolvedTool, ToolRegistry

logger = logging.getLogger(__name__)

MAX_RESULT_SIZE = 32 * 1024  # 32KB
MAX_CONCURRENCY = 5

# Type alias for the tool executor function signature
ToolExecutorFn = Callable[
    [ResolvedTool, dict[str, Any], ToolContext],
    Coroutine[Any, Any, Any],
]


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


class ExecutionEngine:
    """Executes agent invocations via the LLM function-calling loop."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        config: GatewayConfig,
    ) -> None:
        self._llm = llm_client
        self._registry = tool_registry
        self._config = config

    async def execute(
        self,
        agent: AgentDefinition,
        message: str,
        workspace: WorkspaceState,
        context: dict[str, Any] | None = None,
        options: ExecutionOptions | None = None,
        handle: ExecutionHandle | None = None,
        tool_executor: ToolExecutorFn | None = None,
    ) -> ExecutionResult:
        """Run the full agent execution loop.

        Args:
            agent: The agent definition to execute.
            message: The user's message.
            workspace: The loaded workspace state.
            context: Optional context dict from the request.
            options: Execution options (timeout, output_schema, etc.).
            handle: Optional handle for cancellation.
            tool_executor: Optional callable to execute tools. If not provided,
                tools are not executed (useful for testing).
        """
        if options is None:
            options = ExecutionOptions()

        execution_id = handle.execution_id if handle else str(uuid.uuid4())
        usage = UsageAccumulator()
        guardrails = self._config.guardrails

        # Resolve timeout
        timeout_s = (options.timeout_ms or guardrails.timeout_ms) / 1000.0
        max_iterations = guardrails.max_iterations
        max_tool_calls = guardrails.max_tool_calls

        # Build system prompt
        system_prompt = assemble_system_prompt(agent, workspace)
        if options.output_schema:
            system_prompt += build_schema_instruction(options.output_schema)

        # Build tool declarations
        skill_tool_names = self._resolve_skill_tools(agent, workspace)
        resolved_tools = self._registry.resolve_for_agent(agent.id, skill_tool_names, agent.tools)
        tool_declarations = self._registry.to_llm_declarations(resolved_tools)
        tool_map = {t.name: t for t in resolved_tools}

        # Resolve model params
        model, temperature, max_tokens = self._llm.resolve_model_params(agent.model)

        # Build initial messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]

        # Tool context for executors
        tool_context = ToolContext(
            execution_id=execution_id,
            agent_id=agent.id,
            metadata=context or {},
        )

        total_tool_calls = 0
        last_text: str = ""

        try:
            async with asyncio.timeout(timeout_s):
                for _iteration in range(max_iterations):
                    # Check cancellation
                    if handle and handle.is_cancelled:
                        return ExecutionResult(
                            raw_text=last_text,
                            stop_reason=StopReason.CANCELLED,
                            usage=usage,
                        )

                    # Call LLM
                    try:
                        llm_response = await self._llm.completion(
                            messages=messages,
                            tools=tool_declarations or None,
                            model=model,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                    except Exception as e:
                        logger.error("LLM call failed during execution: %s", e)
                        return ExecutionResult(
                            raw_text=last_text,
                            stop_reason=StopReason.ERROR,
                            usage=usage,
                            error="LLM call failed",
                        )

                    # Check cancellation after LLM call
                    if handle and handle.is_cancelled:
                        return ExecutionResult(
                            raw_text=last_text,
                            stop_reason=StopReason.CANCELLED,
                            usage=usage,
                        )

                    # Record usage
                    usage.add_llm_usage(
                        model=llm_response.model,
                        input_tokens=llm_response.input_tokens,
                        output_tokens=llm_response.output_tokens,
                        cost=llm_response.cost,
                    )

                    # Track last text
                    if llm_response.text:
                        last_text = llm_response.text

                    # No tool calls → completion
                    if not llm_response.tool_calls:
                        result = self._build_completion_result(
                            last_text, usage, options.output_schema
                        )
                        # If output schema validation failed, retry once
                        if (
                            options.output_schema
                            and result.validation_errors
                            and result.output is None
                        ):
                            retry_result = await self._retry_structured_output(
                                messages=messages,
                                schema=options.output_schema,
                                errors=result.validation_errors,
                                model=model,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                usage=usage,
                            )
                            if retry_result is not None:
                                return retry_result
                        return result

                    # Process tool calls
                    # Build assistant message with tool calls
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
                            for tc in llm_response.tool_calls
                        ],
                    }
                    if llm_response.text:
                        assistant_msg["content"] = llm_response.text
                    messages.append(assistant_msg)

                    # Execute tools (parallel with bounded concurrency)
                    tool_results = await self._execute_tool_calls(
                        tool_calls=llm_response.tool_calls,
                        tool_map=tool_map,
                        tool_context=tool_context,
                        tool_executor=tool_executor,
                        total_tool_calls=total_tool_calls,
                        max_tool_calls=max_tool_calls,
                        usage=usage,
                    )

                    total_tool_calls += len(tool_results)

                    # Check cancellation after tool execution
                    if handle and handle.is_cancelled:
                        return ExecutionResult(
                            raw_text=last_text,
                            stop_reason=StopReason.CANCELLED,
                            usage=usage,
                        )

                    # Append tool results to messages
                    for tr in tool_results:
                        output_str = _truncate_result(_serialize_tool_output(tr.output))
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tr.call_id,
                                "content": output_str,
                            }
                        )

                    # Check if max tool calls exceeded
                    if total_tool_calls >= max_tool_calls:
                        return ExecutionResult(
                            raw_text=last_text,
                            stop_reason=StopReason.MAX_TOOL_CALLS,
                            usage=usage,
                        )

                # Loop exhausted
                return ExecutionResult(
                    raw_text=last_text,
                    stop_reason=StopReason.MAX_ITERATIONS,
                    usage=usage,
                )

        except TimeoutError:
            return ExecutionResult(
                raw_text=last_text,
                stop_reason=StopReason.TIMEOUT,
                usage=usage,
            )
        except asyncio.CancelledError:
            return ExecutionResult(
                raw_text=last_text,
                stop_reason=StopReason.CANCELLED,
                usage=usage,
            )

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        tool_map: dict[str, ResolvedTool],
        tool_context: ToolContext,
        tool_executor: ToolExecutorFn | None,
        total_tool_calls: int,
        max_tool_calls: int,
        usage: UsageAccumulator,
    ) -> list[ToolResult]:
        """Execute tool calls with bounded concurrency."""
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        results: list[ToolResult] = []

        async def _run_one(tc: ToolCall) -> ToolResult:
            async with semaphore:
                return await self._execute_single_tool(
                    tc, tool_map, tool_context, tool_executor, usage
                )

        if len(tool_calls) == 1:
            # Single tool call — no need for TaskGroup
            results.append(await _run_one(tool_calls[0]))
        else:
            # Parallel execution
            tasks: list[asyncio.Task[ToolResult]] = []
            async with asyncio.TaskGroup() as tg:
                for tc in tool_calls:
                    if total_tool_calls + len(tasks) >= max_tool_calls:
                        # Return error for calls that exceed the limit
                        results.append(
                            ToolResult(
                                call_id=tc.call_id,
                                name=tc.name,
                                success=False,
                                output={"error": "Max tool calls limit reached"},
                            )
                        )
                        continue
                    tasks.append(tg.create_task(_run_one(tc)))

            results.extend(t.result() for t in tasks)

        return results

    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        tool_map: dict[str, ResolvedTool],
        tool_context: ToolContext,
        tool_executor: ToolExecutorFn | None,
        usage: UsageAccumulator,
    ) -> ToolResult:
        """Execute a single tool call with error isolation."""
        start = time.monotonic()

        # Check tool exists
        resolved = tool_map.get(tool_call.name)
        if resolved is None:
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=False,
                output={"error": f"Unknown tool: '{tool_call.name}'"},
            )

        # Check permission (already filtered, but double-check)
        if not resolved.allows_agent(tool_context.agent_id):
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=False,
                output={"error": f"Tool '{tool_call.name}' is not permitted for this agent"},
            )

        # Validate arguments against schema
        if resolved.parameters_schema:
            try:
                jsonschema.validate(
                    instance=tool_call.arguments,
                    schema=resolved.parameters_schema,
                )
            except jsonschema.ValidationError as e:
                return ToolResult(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    success=False,
                    output={
                        "error": f"Invalid arguments for tool '{tool_call.name}': {e.message}"
                    },
                )

        # Execute via tool executor
        if tool_executor is None:
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=False,
                output={"error": "No tool executor configured"},
            )

        try:
            usage.add_tool_call()
            result = await tool_executor(resolved, tool_call.arguments, tool_context)
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=True,
                output=result,
                duration_ms=duration_ms,
            )
        except TimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning("Tool '%s' timed out after %dms", tool_call.name, duration_ms)
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=False,
                output={"error": f"Tool '{tool_call.name}' timed out"},
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error("Tool '%s' failed: %s: %s", tool_call.name, type(e).__name__, e)
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=False,
                output={"error": f"Tool '{tool_call.name}' failed unexpectedly"},
                duration_ms=duration_ms,
            )

    async def _retry_structured_output(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        errors: list[str],
        model: str | None,
        temperature: float,
        max_tokens: int,
        usage: UsageAccumulator,
    ) -> ExecutionResult | None:
        """Retry once to get valid structured output. Returns None if retry also fails."""
        correction = build_correction_message(errors, schema)
        retry_messages = [*messages, correction]

        try:
            llm_response = await self._llm.completion(
                messages=retry_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.error("Structured output retry failed: %s", e)
            return ExecutionResult(
                stop_reason=StopReason.ERROR,
                usage=usage,
                error="Structured output retry failed",
            )

        usage.add_llm_usage(
            model=llm_response.model,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
            cost=llm_response.cost,
        )

        raw = llm_response.text or ""
        output, validation_errors = validate_output(raw, schema)

        if validation_errors:
            # Retry also failed
            return ExecutionResult(
                raw_text=raw,
                stop_reason=StopReason.COMPLETED,
                usage=usage,
                validation_errors=validation_errors,
            )

        return ExecutionResult(
            output=output,
            raw_text=raw,
            stop_reason=StopReason.COMPLETED,
            usage=usage,
        )

    def _build_completion_result(
        self,
        text: str,
        usage: UsageAccumulator,
        output_schema: dict[str, Any] | None,
    ) -> ExecutionResult:
        """Build a completion result, optionally validating against output schema."""
        if not output_schema:
            return ExecutionResult(
                raw_text=text,
                stop_reason=StopReason.COMPLETED,
                usage=usage,
            )

        output, validation_errors = validate_output(text, output_schema)
        return ExecutionResult(
            output=output,
            raw_text=text,
            stop_reason=StopReason.COMPLETED,
            usage=usage,
            validation_errors=validation_errors or None,
        )

    def _resolve_skill_tools(self, agent: AgentDefinition, workspace: WorkspaceState) -> list[str]:
        """Gather tool names from all skills an agent uses."""
        tool_names: list[str] = []
        for skill_name in agent.skills:
            skill = workspace.skills.get(skill_name)
            if skill:
                tool_names.extend(skill.tools)
        return tool_names
