"""Tests for the LLM client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_gateway.config import GatewayConfig, ModelConfig
from agent_gateway.engine.llm import (
    LLMClient,
    _build_model_list,
    _parse_tool_calls,
)
from agent_gateway.exceptions import ExecutionError
from agent_gateway.workspace.agent import AgentModelConfig


class TestBuildModelList:
    def test_default_only(self) -> None:
        config = ModelConfig(default="gpt-4o-mini")
        models, fallbacks = _build_model_list(config)
        assert len(models) == 1
        assert models[0]["model_name"] == "default"
        assert models[0]["litellm_params"]["model"] == "gpt-4o-mini"
        assert fallbacks == []

    def test_with_fallback(self) -> None:
        config = ModelConfig(default="gpt-4o", fallback="claude-3-haiku")
        models, fallbacks = _build_model_list(config)
        assert len(models) == 2
        assert models[1]["model_name"] == "fallback"
        assert models[1]["litellm_params"]["model"] == "claude-3-haiku"
        assert fallbacks == [{"default": ["fallback"]}]

    def test_agent_model_registered(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [AgentModelConfig(name="claude-3-5-sonnet")]
        models, _ = _build_model_list(config, agent_models)
        names = [m["model_name"] for m in models]
        assert "claude-3-5-sonnet" in names

    def test_agent_model_same_as_default_skipped(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [AgentModelConfig(name="gpt-4o")]
        models, _ = _build_model_list(config, agent_models)
        assert len(models) == 1  # only "default"

    def test_agent_model_deduplicated(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [
            AgentModelConfig(name="claude-3"),
            AgentModelConfig(name="claude-3"),
        ]
        models, _ = _build_model_list(config, agent_models)
        claude_entries = [m for m in models if m["model_name"] == "claude-3"]
        assert len(claude_entries) == 1

    def test_reserved_name_default_skipped(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [AgentModelConfig(name="default")]
        models, _ = _build_model_list(config, agent_models)
        assert len(models) == 1  # only the real "default"

    def test_reserved_name_fallback_skipped(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [AgentModelConfig(name="fallback")]
        models, _ = _build_model_list(config, agent_models)
        assert len(models) == 1

    def test_reserved_fallback_name_default_skipped(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [AgentModelConfig(name="claude-3", fallback="default")]
        models, fallbacks = _build_model_list(config, agent_models)
        # "default" should not be re-registered as a model deployment
        default_entries = [m for m in models if m["model_name"] == "default"]
        assert len(default_entries) == 1  # only the original "default"
        # No fallback rule should be created for a reserved name
        assert fallbacks == []

    def test_reserved_fallback_name_fallback_skipped(self) -> None:
        config = ModelConfig(default="gpt-4o", fallback="gpt-3.5-turbo")
        agent_models = [AgentModelConfig(name="claude-3", fallback="fallback")]
        models, fallbacks = _build_model_list(config, agent_models)
        # "fallback" should not be re-registered
        fallback_entries = [m for m in models if m["model_name"] == "fallback"]
        assert len(fallback_entries) == 1  # only the original global fallback
        # Only the global default->fallback rule, no agent fallback rule
        assert fallbacks == [{"default": ["fallback"]}]

    def test_agent_fallback_registered(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [AgentModelConfig(name="claude-3", fallback="claude-3-haiku")]
        models, fallbacks = _build_model_list(config, agent_models)
        names = [m["model_name"] for m in models]
        assert "claude-3-haiku" in names
        assert {"claude-3": ["claude-3-haiku"]} in fallbacks

    def test_agent_fallback_deduplicated(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [
            AgentModelConfig(name="claude-3", fallback="claude-3-haiku"),
            AgentModelConfig(name="gemini-pro", fallback="claude-3-haiku"),
        ]
        models, _ = _build_model_list(config, agent_models)
        haiku_entries = [m for m in models if m["model_name"] == "claude-3-haiku"]
        assert len(haiku_entries) == 1

    def test_agent_fallback_equals_default_normalized(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [AgentModelConfig(name="claude-3", fallback="gpt-4o")]
        models, fallbacks = _build_model_list(config, agent_models)
        assert {"claude-3": ["default"]} in fallbacks
        # gpt-4o should not be registered again under its own name
        names = [m["model_name"] for m in models]
        assert "gpt-4o" not in names

    def test_agent_model_none_name_skipped(self) -> None:
        config = ModelConfig(default="gpt-4o")
        agent_models = [AgentModelConfig()]
        models, _ = _build_model_list(config, agent_models)
        assert len(models) == 1


class TestParseToolCalls:
    def test_no_tool_calls(self) -> None:
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(tool_calls=None))]
        assert _parse_tool_calls(response) == []

    def test_empty_choices(self) -> None:
        response = MagicMock()
        response.choices = []
        assert _parse_tool_calls(response) == []

    def test_single_tool_call(self) -> None:
        tc = MagicMock()
        tc.function.name = "echo"
        tc.function.arguments = '{"message": "hello"}'
        tc.id = "call_123"

        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(tool_calls=[tc]))]

        result = _parse_tool_calls(response)
        assert len(result) == 1
        assert result[0].name == "echo"
        assert result[0].arguments == {"message": "hello"}
        assert result[0].call_id == "call_123"

    def test_malformed_arguments(self) -> None:
        tc = MagicMock()
        tc.function.name = "echo"
        tc.function.arguments = "not json"
        tc.id = "call_1"

        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(tool_calls=[tc]))]

        result = _parse_tool_calls(response)
        assert len(result) == 1
        assert result[0].arguments == {"_raw": "not json"}


class TestLLMClientResolveModelParams:
    def test_defaults(self) -> None:
        config = GatewayConfig(model=ModelConfig(temperature=0.2, max_tokens=2048))
        client = LLMClient(config)
        model, temp, tokens = client.resolve_model_params(None)
        assert model is None
        assert temp == 0.2
        assert tokens == 2048

    def test_agent_overrides(self) -> None:
        config = GatewayConfig(model=ModelConfig(temperature=0.2, max_tokens=2048))
        client = LLMClient(config)
        agent_model = AgentModelConfig(name="claude-3", temperature=0.5, max_tokens=1000)
        model, temp, tokens = client.resolve_model_params(agent_model)
        assert model == "claude-3"
        assert temp == 0.5
        assert tokens == 1000

    def test_partial_agent_overrides(self) -> None:
        config = GatewayConfig(model=ModelConfig(temperature=0.2, max_tokens=2048))
        client = LLMClient(config)
        agent_model = AgentModelConfig(temperature=0.8)
        model, temp, tokens = client.resolve_model_params(agent_model)
        assert model is None
        assert temp == 0.8
        assert tokens == 2048

    def test_agent_model_same_as_default_normalizes_to_none(self) -> None:
        config = GatewayConfig(
            model=ModelConfig(default="gpt-4o", temperature=0.2, max_tokens=2048)
        )
        client = LLMClient(config)
        agent_model = AgentModelConfig(name="gpt-4o")
        model, _, _ = client.resolve_model_params(agent_model)
        assert model is None


class TestLLMClientCompletion:
    @pytest.mark.asyncio
    async def test_completion_raises_on_failure(self) -> None:
        config = GatewayConfig()
        client = LLMClient(config)

        with (
            patch.object(client._router, "acompletion", side_effect=Exception("API error")),
            pytest.raises(ExecutionError, match="LLM call failed"),
        ):
            await client.completion(messages=[{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_completion_success(self) -> None:
        config = GatewayConfig()
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello!", tool_calls=None))]
        mock_response.usage = MagicMock(prompt_tokens=5, completion_tokens=10)
        mock_response.model = "gpt-4o-mini"

        with (
            patch.object(client._router, "acompletion", return_value=mock_response),
            patch("agent_gateway.engine.llm.litellm.completion_cost", return_value=0.001),
        ):
            result = await client.completion(messages=[{"role": "user", "content": "hi"}])

        assert result.text == "Hello!"
        assert result.tool_calls == []
        assert result.model == "gpt-4o-mini"
        assert result.input_tokens == 5
        assert result.output_tokens == 10
