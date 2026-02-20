"""Workflow executor — runs skill step-based workflows.

When a skill defines ``steps`` in its frontmatter, the WorkflowExecutor
runs each step in order: tool invocations, parallel fan-out/fan-in, and
LLM prompt-only steps. Results flow forward via a context dict that
supports JSONPath-like references (``$.input.*``, ``$.steps.<name>.output``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any, Protocol, TypedDict

from agent_gateway.engine.models import ToolContext
from agent_gateway.engine.resolver import resolve_input
from agent_gateway.workspace.registry import ResolvedTool, ToolRegistry
from agent_gateway.workspace.skill import SkillDefinition, SkillStep

logger = logging.getLogger(__name__)

MAX_PARALLEL_TOOLS = 10

# Type alias matching ExecutionEngine's tool executor
ToolExecutorFn = Callable[
    [ResolvedTool, dict[str, Any], ToolContext],
    Coroutine[Any, Any, Any],
]


class WorkflowResult(TypedDict, total=False):
    """Result of a workflow execution."""

    output: Any
    steps: dict[str, Any]
    error: str


class LLMCompletionFn(Protocol):
    """Protocol for the LLM completion callable used by workflow prompt steps."""

    async def __call__(self, *, messages: list[dict[str, Any]]) -> Any: ...


class WorkflowExecutor:
    """Executes a skill's step-based workflow."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutorFn,
        llm_completion: LLMCompletionFn,
    ) -> None:
        self._registry = tool_registry
        self._tool_executor = tool_executor
        self._llm_completion = llm_completion

    async def execute(
        self,
        skill: SkillDefinition,
        input_data: dict[str, Any],
        tool_context: ToolContext,
        timeout_s: float = 300.0,
    ) -> WorkflowResult:
        """Run all steps in order, returning the aggregated results.

        Args:
            skill: The skill definition with steps.
            input_data: Input values passed to the workflow.
            tool_context: Context for tool execution.
            timeout_s: Overall timeout for the entire workflow.

        Returns:
            ``WorkflowResult`` with ``output`` (last step's output) and
            ``steps`` (all step results). On timeout, also includes ``error``.
        """
        context: dict[str, Any] = {
            "input": input_data,
            "steps": {},
        }

        try:
            async with asyncio.timeout(timeout_s):
                for step in skill.steps:
                    step_result = await self._execute_step(step, context, tool_context)
                    context["steps"][step.name] = {"output": step_result}
        except TimeoutError:
            logger.warning("Workflow '%s' timed out after %.0fs", skill.id, timeout_s)
            return WorkflowResult(
                output=None,
                steps=context["steps"],
                error=f"Workflow timed out after {timeout_s}s",
            )

        # Return last step's output as the workflow output
        last_step = skill.steps[-1] if skill.steps else None
        last_output = context["steps"].get(last_step.name, {}).get("output") if last_step else None

        return WorkflowResult(output=last_output, steps=context["steps"])

    async def _execute_step(
        self,
        step: SkillStep,
        context: dict[str, Any],
        tool_context: ToolContext,
    ) -> Any:
        """Execute a single workflow step."""
        start = time.monotonic()

        if step.tool is not None:
            result = await self._execute_tool_step(step, context, tool_context)
        elif step.tools is not None:
            result = await self._execute_parallel_step(step, context, tool_context)
        elif step.prompt is not None:
            result = await self._execute_prompt_step(step, context)
        else:
            logger.error("Step '%s' has no tool, tools, or prompt", step.name)
            result = {"error": f"Invalid step configuration: {step.name}"}

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.debug("Step '%s' completed in %dms", step.name, duration_ms)
        return result

    async def _execute_tool_step(
        self,
        step: SkillStep,
        context: dict[str, Any],
        tool_context: ToolContext,
    ) -> Any:
        """Execute a single-tool step."""
        assert step.tool is not None

        resolved_tool = self._registry.get(step.tool)
        if resolved_tool is None:
            return {"error": f"Tool '{step.tool}' not found"}

        arguments = resolve_input(step.input, context)
        return await self._run_tool(resolved_tool, arguments, tool_context)

    async def _execute_parallel_step(
        self,
        step: SkillStep,
        context: dict[str, Any],
        tool_context: ToolContext,
    ) -> list[Any]:
        """Execute a parallel fan-out step — run multiple tools concurrently."""
        assert step.tools is not None

        if len(step.tools) > MAX_PARALLEL_TOOLS:
            return [
                {"error": f"Parallel step '{step.name}' exceeds max tools ({MAX_PARALLEL_TOOLS})"}
            ]

        async def _run_one(tool_step_idx: int) -> Any:
            try:
                ts = step.tools[tool_step_idx]  # type: ignore[index]
                resolved = self._registry.get(ts.tool)
                if resolved is None:
                    return {"error": f"Tool '{ts.tool}' not found"}
                arguments = resolve_input(ts.input, context)
                return await self._run_tool(resolved, arguments, tool_context)
            except Exception as e:
                logger.error(
                    "Parallel tool %d in step '%s' failed: %s",
                    tool_step_idx,
                    step.name,
                    e,
                )
                return {"error": "Parallel tool execution failed"}

        if len(step.tools) == 1:
            return [await _run_one(0)]

        tasks: list[asyncio.Task[Any]] = []
        async with asyncio.TaskGroup() as tg:
            for i in range(len(step.tools)):
                tasks.append(tg.create_task(_run_one(i)))

        return [t.result() for t in tasks]

    async def _execute_prompt_step(
        self,
        step: SkillStep,
        context: dict[str, Any],
    ) -> Any:
        """Execute an LLM prompt-only step (no tool calls)."""
        assert step.prompt is not None

        # Resolve any input references and build prompt
        resolved_inputs = resolve_input(step.input, context)

        user_content = step.prompt
        if resolved_inputs:
            context_block = json.dumps(resolved_inputs, indent=2, default=str)
            user_content = f"{step.prompt}\n\n## Context\n```json\n{context_block}\n```"

        system_content = step.system_prompt or "You are a workflow step. Respond concisely."
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        try:
            response = await self._llm_completion(messages=messages)
            return response.text or ""
        except Exception as e:
            logger.error("Prompt step '%s' failed: %s", step.name, e)
            return {"error": "LLM call failed"}

    async def _run_tool(
        self,
        tool: ResolvedTool,
        arguments: dict[str, Any],
        tool_context: ToolContext,
    ) -> Any:
        """Execute a tool and return its output."""
        try:
            return await self._tool_executor(tool, arguments, tool_context)
        except Exception as e:
            logger.error("Tool '%s' failed in workflow: %s", tool.name, e)
            return {"error": f"Tool '{tool.name}' failed"}
