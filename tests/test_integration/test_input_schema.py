"""Integration tests for agent input schema validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agent_gateway.exceptions import InputValidationError
from agent_gateway.gateway import Gateway

from .conftest import make_llm_response, make_test_client

SCHEMA_AGENT_MD = """\
---
input_schema:
  type: object
  properties:
    deal_id:
      type: string
    amount:
      type: number
  required:
    - deal_id
---

# Schema Agent

You process deals. Use the deal_id and amount from input.
"""

NO_SCHEMA_AGENT_MD = """\
# Plain Agent

You answer questions. No schema required.
"""


@pytest.fixture
def schema_workspace(tmp_path: Path) -> Path:
    """Create a workspace with one schema agent and one plain agent."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # Agent with input_schema
    schema_dir = ws / "agents" / "schema-agent"
    schema_dir.mkdir(parents=True)
    (schema_dir / "AGENT.md").write_text(SCHEMA_AGENT_MD)

    # Agent without input_schema
    plain_dir = ws / "agents" / "plain-agent"
    plain_dir.mkdir(parents=True)
    (plain_dir / "AGENT.md").write_text(NO_SCHEMA_AGENT_MD)

    return ws


# -- HTTP invoke validation ---------------------------------------------------


class TestHttpInvokeValidation:
    @pytest.mark.asyncio
    async def test_valid_context_passes(
        self, schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """Valid input passes validation and reaches the LLM."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            responses = [make_llm_response(text="Deal processed.")]
            with mock_llm_completion(responses):
                resp = await client.post(
                    "/v1/agents/schema-agent/invoke",
                    json={
                        "message": "Process this deal",
                        "input": {"deal_id": "D-123", "amount": 50000},
                    },
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "completed"
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_422(self, schema_workspace: Path) -> None:
        """Missing required field returns 422 before execution starts."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            resp = await client.post(
                "/v1/agents/schema-agent/invoke",
                json={
                    "message": "Process this deal",
                    "input": {"amount": 50000},
                },
            )
            assert resp.status_code == 422
            data = resp.json()
            assert data["error"]["code"] == "input_validation_failed"
            assert "deal_id" in data["error"]["message"]
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_empty_context_with_required_returns_422(self, schema_workspace: Path) -> None:
        """Empty input dict when schema has required fields returns 422."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            resp = await client.post(
                "/v1/agents/schema-agent/invoke",
                json={"message": "Process this deal"},
            )
            assert resp.status_code == 422
            data = resp.json()
            assert data["error"]["code"] == "input_validation_failed"
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_wrong_type_returns_422(self, schema_workspace: Path) -> None:
        """Wrong type for a field returns 422."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            resp = await client.post(
                "/v1/agents/schema-agent/invoke",
                json={
                    "message": "Process this deal",
                    "input": {"deal_id": 123},
                },
            )
            assert resp.status_code == 422
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_no_schema_agent_accepts_any_context(
        self, schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """Agent without input_schema accepts any input (backward compat)."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            responses = [make_llm_response(text="Hello!")]
            with mock_llm_completion(responses):
                resp = await client.post(
                    "/v1/agents/plain-agent/invoke",
                    json={
                        "message": "Hi",
                        "input": {"anything": "goes", "number": 42},
                    },
                )
            assert resp.status_code == 200
        finally:
            await client.aclose()
            await gw._shutdown()


# -- Programmatic invoke validation -------------------------------------------


class TestProgrammaticInvokeValidation:
    @pytest.mark.asyncio
    async def test_valid_context_passes(
        self, schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """Valid input passes validation via gw.invoke()."""
        async with Gateway(workspace=str(schema_workspace), auth=False) as gw:
            responses = [make_llm_response(text="Done.")]
            with mock_llm_completion(responses):
                result = await gw.invoke(
                    "schema-agent",
                    "Process deal",
                    input={"deal_id": "D-1", "amount": 100},
                )
            assert result.raw_text == "Done."

    @pytest.mark.asyncio
    async def test_invalid_context_raises_error(self, schema_workspace: Path) -> None:
        """Invalid input raises InputValidationError."""
        async with Gateway(workspace=str(schema_workspace), auth=False) as gw:
            with pytest.raises(InputValidationError, match="deal_id"):
                await gw.invoke(
                    "schema-agent",
                    "Process deal",
                    input={"amount": 100},
                )

    @pytest.mark.asyncio
    async def test_error_has_errors_list(self, schema_workspace: Path) -> None:
        """InputValidationError includes structured errors list."""
        async with Gateway(workspace=str(schema_workspace), auth=False) as gw:
            with pytest.raises(InputValidationError) as exc_info:
                await gw.invoke("schema-agent", "Process", input={})
            assert len(exc_info.value.errors) > 0

    @pytest.mark.asyncio
    async def test_no_schema_agent_accepts_any(
        self, schema_workspace: Path, mock_llm_completion: Any
    ) -> None:
        """Agent without schema accepts any input programmatically."""
        async with Gateway(workspace=str(schema_workspace), auth=False) as gw:
            responses = [make_llm_response(text="Hi!")]
            with mock_llm_completion(responses):
                result = await gw.invoke("plain-agent", "Hi", input={"whatever": True})
            assert result.raw_text == "Hi!"


# -- Introspection API --------------------------------------------------------


class TestIntrospectionInputSchema:
    @pytest.mark.asyncio
    async def test_list_agents_includes_input_schema(self, schema_workspace: Path) -> None:
        """GET /v1/agents returns input_schema for each agent."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            resp = await client.get("/v1/agents")
            assert resp.status_code == 200
            agents = {a["id"]: a for a in resp.json()}

            assert agents["schema-agent"]["input_schema"] is not None
            assert agents["schema-agent"]["input_schema"]["type"] == "object"
            assert "deal_id" in agents["schema-agent"]["input_schema"]["properties"]

            assert agents["plain-agent"]["input_schema"] is None
        finally:
            await client.aclose()
            await gw._shutdown()

    @pytest.mark.asyncio
    async def test_get_agent_includes_input_schema(self, schema_workspace: Path) -> None:
        """GET /v1/agents/{id} returns input_schema."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        client = await make_test_client(gw)
        try:
            resp = await client.get("/v1/agents/schema-agent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["input_schema"] is not None
            assert data["input_schema"]["required"] == ["deal_id"]
        finally:
            await client.aclose()
            await gw._shutdown()


# -- Programmatic registration (set_input_schema) ----------------------------


class DealInputModel(BaseModel):
    deal_id: str
    amount: float = 0.0


class TestSetInputSchema:
    @pytest.mark.asyncio
    async def test_pydantic_model_registration(self, schema_workspace: Path) -> None:
        """set_input_schema with Pydantic model overrides frontmatter."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        gw.set_input_schema("plain-agent", DealInputModel)

        async with gw:
            # plain-agent now has an input_schema
            agent = gw.workspace.agents["plain-agent"]
            assert agent.input_schema is not None
            assert "deal_id" in agent.input_schema["properties"]

            # And it validates
            with pytest.raises(InputValidationError, match="deal_id"):
                await gw.invoke("plain-agent", "Hi", input={})

    @pytest.mark.asyncio
    async def test_dict_schema_registration(self, schema_workspace: Path) -> None:
        """set_input_schema with raw dict works."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        gw.set_input_schema("plain-agent", schema)

        async with gw:
            agent = gw.workspace.agents["plain-agent"]
            assert agent.input_schema is not None
            assert "name" in agent.input_schema["properties"]

    @pytest.mark.asyncio
    async def test_code_schema_overrides_frontmatter(self, schema_workspace: Path) -> None:
        """Code-registered schema overrides AGENT.md frontmatter schema."""
        new_schema = {
            "type": "object",
            "properties": {"custom_field": {"type": "boolean"}},
            "required": ["custom_field"],
        }
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        gw.set_input_schema("schema-agent", new_schema)

        async with gw:
            agent = gw.workspace.agents["schema-agent"]
            assert agent.input_schema is not None
            # Should have the new schema, not the frontmatter one
            assert "custom_field" in agent.input_schema["properties"]
            assert "deal_id" not in agent.input_schema["properties"]

    @pytest.mark.asyncio
    async def test_introspection_reflects_code_schema(self, schema_workspace: Path) -> None:
        """Introspection API shows code-registered schema."""
        gw = Gateway(workspace=str(schema_workspace), auth=False)
        gw.set_input_schema("plain-agent", DealInputModel)
        client = await make_test_client(gw)
        try:
            resp = await client.get("/v1/agents/plain-agent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["input_schema"] is not None
            assert "deal_id" in data["input_schema"]["properties"]
        finally:
            await client.aclose()
            await gw._shutdown()
