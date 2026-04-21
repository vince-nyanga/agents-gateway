"""End-to-end tests: agent's output_schema feeds into ExecutionOptions.

These tests exercise the precedence rules added by the
output_schema-on-AgentDefinition feature — specifically that the merge into
ExecutionOptions happens at the gateway / API layer, NOT inside the
executor, so the executor itself remains schema-agnostic.

The tests here stand in for that merge layer with a tiny helper so the
test doesn't need to spin up a full Gateway instance. The real merge is
covered by gateway-level tests elsewhere.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_gateway.engine.models import ExecutionOptions, StopReason
from agent_gateway.workspace.agent import AgentDefinition
from tests.test_engine.conftest import (
    make_agent,
    make_engine,
    make_llm_response,
    make_workspace,
)


def _merge_output_schema(
    agent: AgentDefinition,
    caller: ExecutionOptions | None,
) -> ExecutionOptions:
    """Replicates the precedence merge performed by Gateway.invoke().

    Precedence: caller.output_schema > agent._pydantic_output_model >
    agent.output_schema > None.
    """
    if caller is None:
        caller = ExecutionOptions()
    if caller.output_schema is None:
        caller.output_schema = agent._pydantic_output_model or agent.output_schema
    return caller


class ResumeExtraction(BaseModel):
    full_name: str
    years_experience: int


RESUME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "full_name": {"type": "string"},
        "years_experience": {"type": "integer", "minimum": 0},
    },
    "required": ["full_name", "years_experience"],
}


class TestAgentFrontmatterOutputSchema:
    @pytest.mark.asyncio
    async def test_agent_schema_applied_when_no_caller_options(self) -> None:
        """Agent has output_schema; caller passes no options → schema wins."""
        engine, _, _ = make_engine(
            responses=[
                make_llm_response(text='{"full_name": "Alex Rivera", "years_experience": 8}')
            ]
        )
        agent = make_agent()
        agent.output_schema = RESUME_SCHEMA
        workspace = make_workspace(agents={agent.id: agent})

        effective = _merge_output_schema(agent, None)
        result = await engine.execute(agent, "parse resume", workspace, options=effective)

        assert result.stop_reason == StopReason.COMPLETED
        assert result.output == {"full_name": "Alex Rivera", "years_experience": 8}
        assert result.validation_errors is None

    @pytest.mark.asyncio
    async def test_caller_options_override_agent_schema(self) -> None:
        """Caller-provided output_schema overrides agent's frontmatter schema."""
        override_schema: dict[str, Any] = {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        }
        engine, _, _ = make_engine(responses=[make_llm_response(text='{"summary": "brief"}')])
        agent = make_agent()
        agent.output_schema = RESUME_SCHEMA  # would fail override
        workspace = make_workspace(agents={agent.id: agent})

        caller = ExecutionOptions(output_schema=override_schema)
        effective = _merge_output_schema(agent, caller)
        assert effective.output_schema is override_schema

        result = await engine.execute(agent, "summarize", workspace, options=effective)
        assert result.output == {"summary": "brief"}

    @pytest.mark.asyncio
    async def test_pydantic_model_preferred_over_dict(self) -> None:
        """When both _pydantic_output_model and output_schema are set, the

        Pydantic class is preferred — it produces a model instance via
        validate_output_pydantic() instead of a plain dict.
        """
        engine, _, _ = make_engine(
            responses=[make_llm_response(text='{"full_name": "Jamie", "years_experience": 3}')]
        )
        agent = make_agent()
        agent.output_schema = RESUME_SCHEMA
        agent._pydantic_output_model = ResumeExtraction
        workspace = make_workspace(agents={agent.id: agent})

        effective = _merge_output_schema(agent, None)
        assert effective.output_schema is ResumeExtraction

        result = await engine.execute(agent, "parse", workspace, options=effective)
        assert isinstance(result.output, ResumeExtraction)
        assert result.output.full_name == "Jamie"
        assert result.output.years_experience == 3

    @pytest.mark.asyncio
    async def test_no_agent_schema_no_caller_options_free_text(self) -> None:
        """Agent has no schema, caller none → free-text, output=None."""
        engine, _, _ = make_engine(responses=[make_llm_response(text="hi there")])
        agent = make_agent()
        workspace = make_workspace(agents={agent.id: agent})

        effective = _merge_output_schema(agent, None)
        assert effective.output_schema is None

        result = await engine.execute(agent, "ping", workspace, options=effective)
        assert result.output is None
        assert result.raw_text == "hi there"

    @pytest.mark.asyncio
    async def test_agent_schema_schema_instruction_injected(self) -> None:
        """The system prompt picks up the schema instruction when the agent
        declares an output_schema."""
        engine, mock_llm, _ = make_engine(
            responses=[make_llm_response(text='{"full_name": "X", "years_experience": 1}')]
        )
        agent = make_agent()
        agent.output_schema = RESUME_SCHEMA
        workspace = make_workspace(agents={agent.id: agent})

        effective = _merge_output_schema(agent, None)
        await engine.execute(agent, "parse", workspace, options=effective)

        # System prompt is the first message; assert SCHEMA_INSTRUCTION is present
        first_call = mock_llm.calls[0]
        system_msg = first_call["messages"][0]
        assert system_msg["role"] == "system"
        assert "Required Output Format" in system_msg["content"]
        assert "years_experience" in system_msg["content"]
