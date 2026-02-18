"""LLM client — wraps LiteLLM for production use with failover and cost tracking."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import litellm
from litellm import ModelResponse
from litellm.router import (  # type: ignore[attr-defined]
    AllowedFailsPolicy,
    RetryPolicy,
    Router,
)

from agent_gateway.config import GatewayConfig, ModelConfig
from agent_gateway.engine.models import ToolCall
from agent_gateway.exceptions import ExecutionError
from agent_gateway.workspace.agent import AgentModelConfig

logger = logging.getLogger(__name__)

# Suppress LiteLLM's verbose output
litellm.suppress_debug_info = True


@dataclass
class LLMResponse:
    """Parsed response from an LLM call."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


def _build_model_list(config: ModelConfig) -> list[dict[str, Any]]:
    """Build LiteLLM Router model_list from gateway config."""
    models: list[dict[str, Any]] = [
        {
            "model_name": "default",
            "litellm_params": {"model": config.default},
        }
    ]
    if config.fallback:
        models.append(
            {
                "model_name": "fallback",
                "litellm_params": {"model": config.fallback},
            }
        )
    return models


def _parse_tool_calls(response: ModelResponse) -> list[ToolCall]:
    """Extract tool calls from an LLM response."""
    tool_calls: list[ToolCall] = []
    choices = response.choices
    if not choices:
        return tool_calls

    message = choices[0].message
    if not message or not message.tool_calls:
        return tool_calls

    for tc in message.tool_calls:
        args = tc.function.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = {"_raw": args}

        tool_calls.append(
            ToolCall(
                name=tc.function.name,
                arguments=args if isinstance(args, dict) else {"_raw": args},
                call_id=tc.id or "",
            )
        )
    return tool_calls


def _extract_cost(response: ModelResponse) -> float:
    """Extract cost from response, falling back to litellm.completion_cost."""
    try:
        return float(litellm.completion_cost(completion_response=response))
    except Exception:
        logger.debug("Could not extract cost from LLM response", exc_info=True)
        return 0.0


class LLMClient:
    """Production LLM client with failover and cost tracking."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        model_list = _build_model_list(config.model)

        fallback_list = []
        if config.model.fallback:
            fallback_list = [{"default": ["fallback"]}]

        self._router = Router(
            model_list=model_list,
            retry_policy=RetryPolicy(
                TimeoutError=2,
                RateLimitError=3,
                ContentPolicyViolationError=0,
                AuthenticationError=0,
            ),
            allowed_fails_policy=AllowedFailsPolicy(
                RateLimitErrorAllowedFails=5,
                TimeoutErrorAllowedFails=3,
            ),
            cooldown_time=60.0,
            fallbacks=fallback_list,
            cache_responses=False,
            set_verbose=False,
        )

    async def completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Make an LLM completion call with automatic failover."""
        kwargs: dict[str, Any] = {
            "model": model or "default",
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            response: ModelResponse = await self._router.acompletion(**kwargs)
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            raise ExecutionError(f"LLM call failed: {e}") from e

        return self._parse_response(response)

    async def stream_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream an LLM completion, yielding chunk events.

        Yields dicts with keys:
        - {"type": "token", "content": str}
        - {"type": "tool_call", "index": int, "name": str, "arguments": str, "call_id": str}
        - {"type": "usage", "input_tokens": int, "output_tokens": int, "cost": float, "model": str}
        """
        kwargs: dict[str, Any] = {
            "model": model or "default",
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            response = await self._router.acompletion(**kwargs)
        except Exception as e:
            logger.error("LLM streaming call failed: %s", e)
            raise ExecutionError(f"LLM streaming call failed: {e}") from e

        # Track tool call state for accumulation
        active_tool_calls: dict[int, dict[str, str]] = {}
        accumulated_model = ""
        accumulated_input_tokens = 0
        accumulated_output_tokens = 0

        async for chunk in response:
            # Extract model info
            if hasattr(chunk, "model") and chunk.model:
                accumulated_model = chunk.model

            # Extract usage from final chunk
            if hasattr(chunk, "usage") and chunk.usage:
                accumulated_input_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                accumulated_output_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0

            choices = chunk.choices
            if not choices:
                continue

            delta = choices[0].delta
            if delta is None:
                continue

            # Text content
            if delta.content:
                yield {"type": "token", "content": delta.content}

            # Tool calls
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index if hasattr(tc_delta, "index") else 0

                    if idx not in active_tool_calls:
                        # New tool call
                        active_tool_calls[idx] = {
                            "name": "",
                            "arguments": "",
                            "call_id": "",
                        }

                    if tc_delta.id:
                        active_tool_calls[idx]["call_id"] = tc_delta.id

                    if tc_delta.function:
                        if tc_delta.function.name:
                            active_tool_calls[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            active_tool_calls[idx]["arguments"] += tc_delta.function.arguments

            # Check for finish_reason
            if choices[0].finish_reason:
                # Emit completed tool calls
                for idx, tc_data in sorted(active_tool_calls.items()):
                    yield {
                        "type": "tool_call",
                        "index": idx,
                        "name": tc_data["name"],
                        "arguments": tc_data["arguments"],
                        "call_id": tc_data["call_id"],
                    }
                active_tool_calls.clear()

        # Emit final usage
        cost = 0.0
        try:
            if accumulated_model and (accumulated_input_tokens or accumulated_output_tokens):
                prompt_cost, completion_cost = litellm.cost_per_token(
                    model=accumulated_model,
                    prompt_tokens=accumulated_input_tokens,
                    completion_tokens=accumulated_output_tokens,
                )
                cost = float(prompt_cost + completion_cost)
        except Exception:
            logger.debug("Could not extract streaming cost", exc_info=True)

        yield {
            "type": "usage",
            "input_tokens": accumulated_input_tokens,
            "output_tokens": accumulated_output_tokens,
            "cost": cost,
            "model": accumulated_model,
        }

    def resolve_model_params(
        self,
        agent_model: AgentModelConfig | None,
    ) -> tuple[str | None, float, int]:
        """Resolve model, temperature, max_tokens from agent config + gateway defaults."""
        model = None
        temperature = self._config.model.temperature
        max_tokens = self._config.model.max_tokens

        if agent_model:
            if agent_model.name:
                model = agent_model.name
            if agent_model.temperature is not None:
                temperature = agent_model.temperature
            if agent_model.max_tokens is not None:
                max_tokens = agent_model.max_tokens

        return model, temperature, max_tokens

    def _parse_response(self, response: ModelResponse) -> LLMResponse:
        """Parse a LiteLLM ModelResponse into our LLMResponse."""
        choices = response.choices
        text: str | None = None
        if choices and choices[0].message and choices[0].message.content:
            text = choices[0].message.content

        tool_calls = _parse_tool_calls(response)

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        model = response.model or ""

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            model=model,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            cost=_extract_cost(response),
        )

    async def close(self) -> None:
        """Clean up resources."""
        # Router doesn't have a close method, but we include this for future use
        pass
