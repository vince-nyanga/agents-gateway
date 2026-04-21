"""Integration tests for agent output_schema — frontmatter, HTTP, and code API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_gateway.gateway import Gateway

from .conftest import make_llm_response, make_test_client

OUTPUT_SCHEMA_AGENT_MD = """\
---
output_schema:
  type: object
  properties:
    summary:
      type: string
    score:
      type: number
  required:
    - summary
---

# Schema Agent

You summarize things.
"""

BOTH_SCHEMAS_AGENT_MD = """\
---
input_schema:
  type: object
  properties:
    text:
      type: string
  required:
    - text
output_schema:
  type: object
  properties:
    words:
      type: integer
  required:
    - words
---

# Both Agent

You count words.
"""

NO_SCHEMA_AGENT_MD = """\
# Plain Agent

You answer questions. No schema.
"""


@pytest.fixture
def output_schema_workspace(tmp_path: Path) -> Path:
    """Workspace with an agent that has output_schema, one with both, and one without."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    out_dir = ws / "agents" / "summarizer"
    out_dir.mkdir(parents=True)
    (out_dir / "AGENT.md").write_text(OUTPUT_SCHEMA_AGENT_MD)

    both_dir = ws / "agents" / "counter"
    both_dir.mkdir(parents=True)
    (both_dir / "AGENT.md").write_text(BOTH_SCHEMAS_AGENT_MD)

    plain_dir = ws / "agents" / "plain"
    plain_dir.mkdir(parents=True)
    (plain_dir / "AGENT.md").write_text(NO_SCHEMA_AGENT_MD)

    return ws


# -- HTTP invoke applies the schema automatically -----------------------------


class TestHttpInvokeOutputSchema:
    @pytest.mark.asyncio
    async def test_agent_output_schema_applied_without_options(
        self, output_schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """POST /invoke with no options → agent's output_schema is applied."""
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            responses = [make_llm_response(text='{"summary": "ok", "score": 9}')]
            with mock_llm_completion(responses):
                resp = await client.post(
                    "/v1/agents/summarizer/invoke",
                    json={"message": "Summarize this."},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["result"]["output"] == {"summary": "ok", "score": 9}
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_caller_override_beats_agent_schema(
        self, output_schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """options.output_schema in the request body overrides the agent's."""
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            responses = [make_llm_response(text='{"override_field": "yes"}')]
            override_schema = {
                "type": "object",
                "properties": {"override_field": {"type": "string"}},
                "required": ["override_field"],
            }
            with mock_llm_completion(responses):
                resp = await client.post(
                    "/v1/agents/summarizer/invoke",
                    json={
                        "message": "hi",
                        "options": {"output_schema": override_schema},
                    },
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["result"]["output"] == {"override_field": "yes"}
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_validation_errors_surface_on_bad_output(
        self, output_schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """LLM emits invalid JSON twice → 200 with validation_errors populated."""
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            # Two invalid responses — executor retries once, then gives up.
            responses = [
                make_llm_response(text="definitely not json"),
                make_llm_response(text="still garbage"),
            ]
            with mock_llm_completion(responses):
                resp = await client.post(
                    "/v1/agents/summarizer/invoke",
                    json={"message": "summarize"},
                )
            # Execution still 200 — validation failure isn't an exec failure.
            assert resp.status_code == 200
            data = resp.json()
            assert data["result"]["output"] is None
            assert data["result"]["validation_errors"] is not None
            assert len(data["result"]["validation_errors"]) > 0
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_plain_agent_no_schema_free_text(
        self, output_schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """Plain agent returns free text; output is None but raw_text populated."""
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            responses = [make_llm_response(text="just a string response")]
            with mock_llm_completion(responses):
                resp = await client.post(
                    "/v1/agents/plain/invoke",
                    json={"message": "hi"},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["result"]["output"] is None
            assert data["result"]["raw_text"] == "just a string response"
        finally:
            await client.aclose()
            await gw._shutdown()


# -- Programmatic gw.invoke() applies the schema ------------------------------


class TestProgrammaticInvokeOutputSchema:
    @pytest.mark.asyncio
    async def test_agent_schema_applied(
        self, output_schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """gw.invoke() without options picks up agent.output_schema."""
        async with Gateway(workspace=str(output_schema_workspace), auth=False) as gw:
            responses = [make_llm_response(text='{"summary": "done"}')]
            with mock_llm_completion(responses):
                result = await gw.invoke("summarizer", "summarize")
            assert result.output == {"summary": "done"}

    @pytest.mark.asyncio
    async def test_caller_options_override(
        self, output_schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """Explicit ExecutionOptions.output_schema overrides the agent's."""
        from agent_gateway.engine.models import ExecutionOptions

        override = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        }
        async with Gateway(workspace=str(output_schema_workspace), auth=False) as gw:
            responses = [make_llm_response(text='{"x": 7}')]
            with mock_llm_completion(responses):
                result = await gw.invoke(
                    "summarizer",
                    "go",
                    options=ExecutionOptions(output_schema=override),
                )
            assert result.output == {"x": 7}


# -- Introspection ------------------------------------------------------------


class TestIntrospectionOutputSchema:
    @pytest.mark.asyncio
    async def test_list_agents_includes_output_schema(self, output_schema_workspace: Path) -> None:
        """GET /v1/agents returns output_schema for each agent."""
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            resp = await client.get("/v1/agents")
            assert resp.status_code == 200
            agents = {a["id"]: a for a in resp.json()}
            assert agents["summarizer"]["output_schema"] is not None
            assert agents["summarizer"]["output_schema"]["required"] == ["summary"]
            assert agents["plain"]["output_schema"] is None
            # Agent with both schemas populates both.
            assert agents["counter"]["input_schema"] is not None
            assert agents["counter"]["output_schema"] is not None
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_get_agent_includes_output_schema(self, output_schema_workspace: Path) -> None:
        """GET /v1/agents/{id} returns output_schema."""
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            resp = await client.get("/v1/agents/summarizer")
            assert resp.status_code == 200
            data = resp.json()
            assert data["output_schema"] is not None
            assert "summary" in data["output_schema"]["properties"]
        finally:
            await client.aclose()
            await gw._shutdown()


# -- Chat is excluded from schema enforcement --------------------------------


class TestChatExcludedFromOutputSchema:
    @pytest.mark.asyncio
    async def test_chat_does_not_inject_schema_instruction(
        self, output_schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """Even though summarizer has output_schema, /chat must not force JSON.

        We assert the system prompt sent to the LLM does NOT contain the
        schema-instruction marker. This locks in the intentional asymmetry
        between invoke (enforces schema) and chat (free text).
        """
        from unittest.mock import patch

        captured_calls: list[dict[str, Any]] = []

        async def _capture(self: Any, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
            captured_calls.append({"messages": messages, "kwargs": kwargs})
            return make_llm_response(text="a friendly chat reply")

        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            with patch(
                "agent_gateway.engine.llm.LLMClient.completion",
                autospec=True,
                side_effect=_capture,
            ):
                resp = await client.post(
                    "/v1/agents/summarizer/chat",
                    json={"message": "hi"},
                )
            assert resp.status_code == 200
            assert captured_calls, "LLM was not invoked"
            system_msg = captured_calls[0]["messages"][0]
            assert system_msg["role"] == "system"
            assert "Required Output Format" not in system_msg["content"]
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_programmatic_chat_does_not_inject_schema_instruction(
        self, output_schema_workspace: Path
    ) -> None:
        """gw.chat() does not apply agent.output_schema either."""
        from unittest.mock import patch

        captured_calls: list[dict[str, Any]] = []

        async def _capture(self: Any, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
            captured_calls.append({"messages": messages})
            return make_llm_response(text="chat reply")

        async with Gateway(workspace=str(output_schema_workspace), auth=False) as gw:
            with patch(
                "agent_gateway.engine.llm.LLMClient.completion",
                autospec=True,
                side_effect=_capture,
            ):
                session_id, result = await gw.chat("summarizer", "hi")
            assert captured_calls
            system_msg = captured_calls[0]["messages"][0]
            assert "Required Output Format" not in system_msg["content"]
            assert result.raw_text == "chat reply"


# -- Programmatic set_output_schema API --------------------------------------


class SummaryModel(BaseModel):
    summary: str
    rating: int = 0


class TestSetOutputSchema:
    @pytest.mark.asyncio
    async def test_pydantic_model_registration(
        self, output_schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """set_output_schema with Pydantic class overrides frontmatter."""
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        gw.set_output_schema("plain", SummaryModel)

        async with gw:
            agent = gw.workspace.agents["plain"]
            assert agent.output_schema is not None
            assert "summary" in agent.output_schema["properties"]
            assert agent._pydantic_output_model is SummaryModel

            responses = [make_llm_response(text='{"summary": "done", "rating": 5}')]
            with mock_llm_completion(responses):
                result = await gw.invoke("plain", "go")
            assert isinstance(result.output, SummaryModel)
            assert result.output.summary == "done"
            assert result.output.rating == 5

    @pytest.mark.asyncio
    async def test_dict_schema_registration(self, output_schema_workspace: Path) -> None:
        """set_output_schema with a dict works."""
        schema = {
            "type": "object",
            "properties": {"tag": {"type": "string"}},
            "required": ["tag"],
        }
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        gw.set_output_schema("plain", schema)
        async with gw:
            agent = gw.workspace.agents["plain"]
            assert agent.output_schema == schema
            assert agent._pydantic_output_model is None

    @pytest.mark.asyncio
    async def test_code_registration_overrides_frontmatter(
        self, output_schema_workspace: Path
    ) -> None:
        """Code-registered schema overrides AGENT.md frontmatter schema."""
        new_schema = {
            "type": "object",
            "properties": {"completely_different": {"type": "boolean"}},
            "required": ["completely_different"],
        }
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        gw.set_output_schema("summarizer", new_schema)
        async with gw:
            agent = gw.workspace.agents["summarizer"]
            assert agent.output_schema == new_schema
            assert "summary" not in agent.output_schema["properties"]

    @pytest.mark.asyncio
    async def test_unknown_agent_warning_only(
        self, output_schema_workspace: Path, caplog: Any
    ) -> None:
        """Registering for an unknown agent logs a warning but doesn't raise."""
        import logging

        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        gw.set_output_schema("nonexistent-agent", SummaryModel)
        with caplog.at_level(logging.WARNING):
            async with gw:
                pass
        assert any("nonexistent-agent" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_introspection_reflects_pydantic_schema(
        self, output_schema_workspace: Path
    ) -> None:
        """After set_output_schema(Pydantic), introspection shows the JSON Schema."""
        gw = Gateway(workspace=str(output_schema_workspace), auth=False)
        gw.set_output_schema("plain", SummaryModel)
        client = await make_test_client(gw)
        try:
            resp = await client.get("/v1/agents/plain")
            assert resp.status_code == 200
            data = resp.json()
            assert data["output_schema"] is not None
            assert "summary" in data["output_schema"]["properties"]
        finally:
            await client.aclose()
            await gw._shutdown()
