"""Tests for telemetry attribute constants."""

from __future__ import annotations

from agent_gateway.telemetry import attributes as attr


def test_genai_attributes_defined():
    """GenAI semantic convention attributes should be defined."""
    assert attr.GEN_AI_OPERATION_NAME == "gen_ai.operation.name"
    assert attr.GEN_AI_REQUEST_MODEL == "gen_ai.request.model"
    assert attr.GEN_AI_USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"
    assert attr.GEN_AI_USAGE_OUTPUT_TOKENS == "gen_ai.usage.output_tokens"


def test_agw_attributes_defined():
    """Agent Gateway custom attributes should be defined."""
    assert attr.AGW_AGENT_ID == "agw.agent.id"
    assert attr.AGW_EXECUTION_ID == "agw.execution.id"
    assert attr.AGW_TOOL_NAME == "agw.tool.name"
    assert attr.AGW_TOOL_TYPE == "agw.tool.type"


def test_operation_names_defined():
    """Operation name constants should be defined."""
    assert attr.OP_AGENT_INVOKE == "agent.invoke"
    assert attr.OP_LLM_CALL == "llm.call"
    assert attr.OP_TOOL_EXECUTE == "tool.execute"
    assert attr.OP_OUTPUT_VALIDATE == "output.validate"
