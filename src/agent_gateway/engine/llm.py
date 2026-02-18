"""LLM client — wraps LiteLLM for production use with failover and cost tracking."""

from __future__ import annotations

import json
import logging
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
