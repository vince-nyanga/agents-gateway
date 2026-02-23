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
from agent_gateway.context.registry import RetrieverRegistry
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
    resolve_schema,
    validate_output,
    validate_output_pydantic,
)
from agent_gateway.hooks import HookRegistry
from agent_gateway.persistence.domain import ExecutionStep
from agent_gateway.persistence.protocols import ExecutionRepository
from agent_gateway.telemetry import attributes as attr
from agent_gateway.telemetry.metrics import create_metrics
from agent_gateway.telemetry.tracing import (
    agent_invoke_span,
    llm_call_span,
    set_span_error,
    set_span_ok,
    tool_execute_span,
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
        hooks: HookRegistry | None = None,
        retriever_registry: RetrieverRegistry | None = None,
        execution_repo: ExecutionRepository | None = None,
    ) -> None:
        self._llm = llm_client
        self._registry = tool_registry
        self._config = config
        self._hooks = hooks or HookRegistry()
        self._metrics = create_metrics()
        self._retriever_registry = retriever_registry
        self._execution_repo = execution_repo

    async def execute(
        self,
        agent: AgentDefinition,
        message: str,
        workspace: WorkspaceState,
        input: dict[str, Any] | None = None,
        options: ExecutionOptions | None = None,
        handle: ExecutionHandle | None = None,
        tool_executor: ToolExecutorFn | None = None,
        message_history: list[dict[str, Any]] | None = None,
        memory_block: str = "",
        caller_identity: str | None = None,
        user_instructions: str | None = None,
        user_secrets: dict[str, str] | None = None,
        user_config: dict[str, Any] | None = None,
        parent_execution_id: str | None = None,
        root_execution_id: str | None = None,
        delegation_depth: int = 0,
        delegates_to: list[str] | None = None,
    ) -> ExecutionResult:
        """Run the full agent execution loop.

        Args:
            agent: The agent definition to execute.
            message: The user's message (used when message_history is None).
            workspace: The loaded workspace state.
            input: Optional input dict from the request.
            options: Execution options (timeout, output_schema, etc.).
            handle: Optional handle for cancellation.
            tool_executor: Optional callable to execute tools. If not provided,
                tools are not executed (useful for testing).
            message_history: Optional pre-built message list for multi-turn chat.
                When provided, this is used instead of constructing messages from
                system prompt + message. Must include the system prompt as the
                first message and the latest user message.
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

        # Resolve output schema (Pydantic model → JSON Schema dict + model class)
        json_schema: dict[str, Any] | None = None
        model_cls = None
        if options.output_schema:
            json_schema, model_cls = resolve_schema(options.output_schema)

        # Build system prompt
        system_prompt = await assemble_system_prompt(
            agent,
            workspace,
            query=message,
            retriever_registry=self._retriever_registry,
            context_retrieval_config=self._config.context_retrieval,
            memory_block=memory_block,
            user_instructions=user_instructions,
        )
        if json_schema:
            system_prompt += build_schema_instruction(json_schema)

        # Build tool declarations — agents gain tools through skills plus permitted code tools
        skill_tool_names = self._resolve_skill_tools(agent, workspace)
        resolved_tools = self._registry.resolve_for_agent(agent.id, skill_tool_names)

        # Also inject code tools that are permitted for this agent but not surfaced via skills
        # (e.g. delegate_to_agent, memory tools registered directly as CodeTools)
        all_tools = self._registry.get_all()
        for name, tool in all_tools.items():
            if name not in {t.name for t in resolved_tools} and tool.allows_agent(agent.id):
                resolved_tools.append(tool)

        tool_declarations = self._registry.to_llm_declarations(resolved_tools)
        tool_map = {t.name: t for t in resolved_tools}
        logger.debug("Agent '%s' tools: %s", agent.id, list(tool_map.keys()))

        # Resolve model params
        model, temperature, max_tokens = self._llm.resolve_model_params(agent.model)

        # Build initial messages
        if message_history is not None:
            messages = list(message_history)
            # Surface any pre-provided input data (from API chat callers)
            if input and agent.input_schema:
                input_note = (
                    "The caller has pre-provided some input values:\n"
                    f"```json\n{json.dumps(input, indent=2)}\n```\n"
                    "Use these values and only ask for missing required fields."
                )
                # Insert synthetic exchange after the system prompt
                messages.insert(1, {"role": "user", "content": input_note})
                ack = "Understood, I'll use those values."
                messages.insert(2, {"role": "assistant", "content": ack})
        else:
            # Inject structured input into the user message when available
            user_content = message
            if input and agent.input_schema:
                input_block = json.dumps(input, indent=2)
                user_content = f"{message}\n\n## Input\n```json\n{input_block}\n```"

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

        # Tool context for executors
        tool_context = ToolContext(
            execution_id=execution_id,
            agent_id=agent.id,
            caller_identity=caller_identity,
            metadata=input or {},
            user_secrets=user_secrets or {},
            user_config=user_config or {},
            parent_execution_id=parent_execution_id,
            root_execution_id=root_execution_id or execution_id,
            delegation_depth=delegation_depth,
            delegates_to=delegates_to or [],
        )

        exec_start = time.monotonic()

        await self._hooks.fire(
            "agent.invoke.before",
            agent_id=agent.id,
            message=message,
            execution_id=execution_id,
        )

        with agent_invoke_span(agent.id, execution_id) as invoke_span:
            try:
                result = await self._execute_loop(
                    agent=agent,
                    messages=messages,
                    tool_declarations=tool_declarations,
                    tool_map=tool_map,
                    tool_context=tool_context,
                    tool_executor=tool_executor,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    options=options,
                    handle=handle,
                    usage=usage,
                    timeout_s=timeout_s,
                    max_iterations=max_iterations,
                    max_tool_calls=max_tool_calls,
                    execution_id=execution_id,
                    json_schema=json_schema,
                    model_cls=model_cls,
                )
                set_span_ok(invoke_span)
                invoke_span.set_attribute(attr.AGW_STOP_REASON, result.stop_reason.value)
            except Exception as exc:
                set_span_error(invoke_span, exc)
                raise

        duration_ms = int((time.monotonic() - exec_start) * 1000)
        self._metrics.executions_total.add(1, {"agent_id": agent.id})
        self._metrics.executions_duration.record(duration_ms, {"agent_id": agent.id})

        await self._hooks.fire(
            "agent.invoke.after",
            agent_id=agent.id,
            execution_id=execution_id,
            result=result,
            duration_ms=duration_ms,
        )

        return result

    async def _execute_loop(
        self,
        agent: AgentDefinition,
        messages: list[dict[str, Any]],
        tool_declarations: list[dict[str, Any]],
        tool_map: dict[str, ResolvedTool],
        tool_context: ToolContext,
        tool_executor: ToolExecutorFn | None,
        model: str | None,
        temperature: float,
        max_tokens: int,
        options: ExecutionOptions,
        handle: ExecutionHandle | None,
        usage: UsageAccumulator,
        timeout_s: float,
        max_iterations: int,
        max_tool_calls: int,
        execution_id: str | None = None,
        json_schema: dict[str, Any] | None = None,
        model_cls: Any = None,
    ) -> ExecutionResult:
        """Inner execution loop, wrapped by OTel span and hooks in execute()."""
        total_tool_calls = 0
        last_text: str = ""
        step_seq = 0

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

                    # Call LLM with span
                    llm_start = time.monotonic()
                    llm_response = await self._call_llm_with_span(
                        messages=messages,
                        tools=tool_declarations,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        agent_id=agent.id,
                    )
                    llm_duration_ms = int((time.monotonic() - llm_start) * 1000)

                    if llm_response is None:
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

                    # Record LLM call step
                    if self._execution_repo is not None and execution_id is not None:
                        content_preview = (llm_response.text or "")[:2048]
                        await self._execution_repo.add_step(
                            ExecutionStep(
                                execution_id=execution_id,
                                step_type="llm_call",
                                sequence=step_seq,
                                data={
                                    "model": llm_response.model,
                                    "input_tokens": llm_response.input_tokens,
                                    "output_tokens": llm_response.output_tokens,
                                    "cost_usd": llm_response.cost,
                                    "has_tool_calls": len(llm_response.tool_calls) > 0,
                                    "content": content_preview,
                                    "tool_calls_count": len(llm_response.tool_calls),
                                },
                                duration_ms=llm_duration_ms,
                            )
                        )
                        step_seq += 1

                    # No tool calls → completion
                    if not llm_response.tool_calls:
                        result = self._build_completion_result(
                            last_text, usage, json_schema, model_cls
                        )
                        # If output schema validation failed, retry once
                        if json_schema and result.validation_errors and result.output is None:
                            retry_result = await self._retry_structured_output(
                                messages=messages,
                                schema=json_schema,
                                errors=result.validation_errors,
                                model=model,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                usage=usage,
                                model_cls=model_cls,
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

                    # Record tool_call steps before execution
                    if self._execution_repo is not None and execution_id is not None:
                        for tc in llm_response.tool_calls:
                            await self._execution_repo.add_step(
                                ExecutionStep(
                                    execution_id=execution_id,
                                    step_type="tool_call",
                                    sequence=step_seq,
                                    data={
                                        "tool_name": tc.name,
                                        "call_id": tc.call_id,
                                        "arguments": tc.arguments,
                                    },
                                    duration_ms=0,
                                )
                            )
                            step_seq += 1

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

                    # Append tool results to messages and record steps
                    for tr in tool_results:
                        output_str = _truncate_result(_serialize_tool_output(tr.output))
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tr.call_id,
                                "content": output_str,
                            }
                        )
                        if self._execution_repo is not None and execution_id is not None:
                            result_preview = output_str[:2048]
                            truncated = len(output_str) > 2048
                            await self._execution_repo.add_step(
                                ExecutionStep(
                                    execution_id=execution_id,
                                    step_type="tool_result",
                                    sequence=step_seq,
                                    data={
                                        "tool_name": tr.name,
                                        "call_id": tr.call_id,
                                        "success": tr.success,
                                        "result": result_preview,
                                        "truncated": truncated,
                                    },
                                    duration_ms=tr.duration_ms,
                                )
                            )
                            step_seq += 1

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

    async def _call_llm_with_span(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None,
        temperature: float,
        max_tokens: int,
        agent_id: str,
    ) -> Any:
        """Call LLM wrapped with OTel span, metrics, and hooks."""
        model_label = model or "default"

        await self._hooks.fire("llm.call.before", model=model_label, agent_id=agent_id)

        llm_start = time.monotonic()
        with llm_call_span(model_label, agent_id) as span:
            try:
                llm_response = await self._llm.completion(
                    messages=messages,
                    tools=tools or None,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                set_span_error(span, exc)
                logger.error("LLM call failed during execution: %s", exc)
                await self._hooks.fire(
                    "llm.call.after", model=model_label, agent_id=agent_id, error=exc
                )
                return None

            span.set_attribute(attr.GEN_AI_USAGE_INPUT_TOKENS, llm_response.input_tokens)
            span.set_attribute(attr.GEN_AI_USAGE_OUTPUT_TOKENS, llm_response.output_tokens)
            set_span_ok(span)

        llm_duration_ms = int((time.monotonic() - llm_start) * 1000)
        self._metrics.llm_calls_total.add(1, {"model": model_label})
        self._metrics.llm_duration.record(llm_duration_ms, {"model": model_label})
        self._metrics.llm_tokens_input.add(
            llm_response.input_tokens, {"model": model_label, "agent_id": agent_id}
        )
        self._metrics.llm_tokens_output.add(
            llm_response.output_tokens, {"model": model_label, "agent_id": agent_id}
        )
        if llm_response.cost:
            self._metrics.llm_cost_usd.add(
                llm_response.cost, {"model": model_label, "agent_id": agent_id}
            )

        await self._hooks.fire(
            "llm.call.after",
            model=model_label,
            agent_id=agent_id,
            duration_ms=llm_duration_ms,
            input_tokens=llm_response.input_tokens,
            output_tokens=llm_response.output_tokens,
        )

        return llm_response

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

        await self._hooks.fire(
            "tool.execute.before",
            tool_name=tool_call.name,
            agent_id=tool_context.agent_id,
            arguments=tool_call.arguments,
        )

        with tool_execute_span(
            tool_call.name, resolved.source, **{"agw.tool.args": json.dumps(tool_call.arguments)}
        ) as span:
            try:
                usage.add_tool_call()
                result = await tool_executor(resolved, tool_call.arguments, tool_context)
                duration_ms = int((time.monotonic() - start) * 1000)
                set_span_ok(span)

                self._metrics.tools_calls_total.add(1, {"tool": tool_call.name})
                self._metrics.tools_duration.record(duration_ms, {"tool": tool_call.name})

                await self._hooks.fire(
                    "tool.execute.after",
                    tool_name=tool_call.name,
                    agent_id=tool_context.agent_id,
                    duration_ms=duration_ms,
                    success=True,
                )

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
                set_span_error(span, TimeoutError(f"Tool '{tool_call.name}' timed out"))

                self._metrics.tools_calls_total.add(1, {"tool": tool_call.name})
                self._metrics.tools_duration.record(duration_ms, {"tool": tool_call.name})

                await self._hooks.fire(
                    "tool.execute.after",
                    tool_name=tool_call.name,
                    agent_id=tool_context.agent_id,
                    duration_ms=duration_ms,
                    success=False,
                )

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
                set_span_error(span, e)

                self._metrics.tools_calls_total.add(1, {"tool": tool_call.name})
                self._metrics.tools_duration.record(duration_ms, {"tool": tool_call.name})

                await self._hooks.fire(
                    "tool.execute.after",
                    tool_name=tool_call.name,
                    agent_id=tool_context.agent_id,
                    duration_ms=duration_ms,
                    success=False,
                )

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
        model_cls: Any = None,
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
        if model_cls is not None:
            output, validation_errors = validate_output_pydantic(raw, model_cls)
        else:
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
        json_schema: dict[str, Any] | None = None,
        model_cls: Any = None,
    ) -> ExecutionResult:
        """Build a completion result, optionally validating against output schema."""
        if not json_schema:
            return ExecutionResult(
                raw_text=text,
                stop_reason=StopReason.COMPLETED,
                usage=usage,
            )

        if model_cls is not None:
            output, validation_errors = validate_output_pydantic(text, model_cls)
        else:
            output, validation_errors = validate_output(text, json_schema)
        return ExecutionResult(
            output=output,
            raw_text=text,
            stop_reason=StopReason.COMPLETED,
            usage=usage,
            validation_errors=validation_errors or None,
        )

    @staticmethod
    def _resolve_skill_tools(agent: AgentDefinition, workspace: WorkspaceState) -> list[str]:
        """Gather tool names from all skills an agent uses."""
        return workspace.resolve_agent_tools(agent)
