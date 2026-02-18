"""Tests for structured output validation."""

from __future__ import annotations

from typing import Any

import pytest

from agent_gateway.engine.models import StopReason
from agent_gateway.engine.output import (
    build_correction_message,
    build_schema_instruction,
    validate_output,
)
from tests.test_engine.conftest import (
    make_agent,
    make_engine,
    make_llm_response,
    make_workspace,
)

SIMPLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "integer"},
        "explanation": {"type": "string"},
    },
    "required": ["answer"],
}


class TestValidateOutput:
    def test_valid_json_matching_schema(self) -> None:
        raw = '{"answer": 42, "explanation": "The answer"}'
        output, errors = validate_output(raw, SIMPLE_SCHEMA)
        assert output == {"answer": 42, "explanation": "The answer"}
        assert errors == []

    def test_valid_json_missing_required(self) -> None:
        raw = '{"explanation": "No answer"}'
        output, errors = validate_output(raw, SIMPLE_SCHEMA)
        assert output is None
        assert len(errors) == 1
        assert "answer" in errors[0]

    def test_invalid_json(self) -> None:
        raw = "not json at all"
        output, errors = validate_output(raw, SIMPLE_SCHEMA)
        assert output is None
        assert len(errors) == 1
        assert "Invalid JSON" in errors[0]

    def test_wrong_type(self) -> None:
        raw = '{"answer": "not an integer"}'
        output, errors = validate_output(raw, SIMPLE_SCHEMA)
        assert output is None
        assert len(errors) == 1

    def test_empty_string(self) -> None:
        output, errors = validate_output("", SIMPLE_SCHEMA)
        assert output is None
        assert len(errors) == 1


class TestBuildSchemaInstruction:
    def test_includes_schema(self) -> None:
        instruction = build_schema_instruction(SIMPLE_SCHEMA)
        assert "Required Output Format" in instruction
        assert '"answer"' in instruction
        assert "integer" in instruction


class TestBuildCorrectionMessage:
    def test_correction_message(self) -> None:
        msg = build_correction_message(["Missing field: answer"], SIMPLE_SCHEMA)
        assert msg["role"] == "user"
        assert "Missing field: answer" in msg["content"]
        assert '"answer"' in msg["content"]


class TestStructuredOutputInExecution:
    @pytest.mark.asyncio
    async def test_valid_output_schema(self) -> None:
        """LLM returns valid JSON matching schema → output populated."""
        engine, _, _ = make_engine(responses=[make_llm_response(text='{"answer": 42}')])
        agent = make_agent()
        workspace = make_workspace()
        from agent_gateway.engine.models import ExecutionOptions

        options = ExecutionOptions(output_schema=SIMPLE_SCHEMA)
        result = await engine.execute(agent, "What is 6*7?", workspace, options=options)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.output == {"answer": 42}
        assert result.validation_errors is None

    @pytest.mark.asyncio
    async def test_invalid_then_retry_success(self) -> None:
        """LLM returns invalid JSON → retry → valid JSON → output populated."""
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(text="not json"),
                make_llm_response(text='{"answer": 42}'),
            ]
        )
        agent = make_agent()
        workspace = make_workspace()
        from agent_gateway.engine.models import ExecutionOptions

        options = ExecutionOptions(output_schema=SIMPLE_SCHEMA)
        result = await engine.execute(agent, "What is 6*7?", workspace, options=options)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.output == {"answer": 42}

    @pytest.mark.asyncio
    async def test_invalid_then_retry_also_fails(self) -> None:
        """LLM returns invalid twice → output=None, validation_errors populated."""
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(text="not json"),
                make_llm_response(text="still not json"),
            ]
        )
        agent = make_agent()
        workspace = make_workspace()
        from agent_gateway.engine.models import ExecutionOptions

        options = ExecutionOptions(output_schema=SIMPLE_SCHEMA)
        result = await engine.execute(agent, "What is 6*7?", workspace, options=options)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.output is None
        assert result.validation_errors is not None
        assert len(result.validation_errors) > 0

    @pytest.mark.asyncio
    async def test_no_schema(self) -> None:
        """No output_schema → raw_text only, output=None."""
        engine, _, _ = make_engine(responses=[make_llm_response(text="Just text")])
        agent = make_agent()
        workspace = make_workspace()

        result = await engine.execute(agent, "Hi", workspace)

        assert result.output is None
        assert result.raw_text == "Just text"
