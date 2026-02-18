"""Tests for the Gateway stub."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel

from agent_gateway import Gateway, __version__


class _ToolInput(BaseModel):
    """Module-level model for testing."""

    query: str
    limit: int = 10


class TestGatewayStub:
    def test_gateway_is_fastapi(self) -> None:
        from fastapi import FastAPI

        gw = Gateway()
        assert isinstance(gw, FastAPI)

    def test_gateway_default_params(self) -> None:
        gw = Gateway()
        assert gw._workspace_path == "./workspace"
        assert gw._auth_enabled is True
        assert gw._reload_enabled is False

    def test_gateway_custom_params(self) -> None:
        gw = Gateway(workspace="./my-agents", auth=False, reload=True, title="Test")
        assert gw._workspace_path == "./my-agents"
        assert gw._auth_enabled is False
        assert gw._reload_enabled is True
        assert gw.title == "Test"

    def test_version(self) -> None:
        # __version__ is "0.0.0" at dev time, replaced by GitVersion at build time
        assert isinstance(__version__, str)
        assert len(__version__.split(".")) >= 3

    def test_pending_tools_initialized(self) -> None:
        gw = Gateway()
        assert gw._pending_tools == []


class TestGatewayToolDecorator:
    def test_tool_decorator_bare(self) -> None:
        """@gw.tool — bare decorator (no parens)."""
        gw = Gateway()

        @gw.tool
        async def echo(message: str) -> dict[str, Any]:
            """Echo a message back."""
            return {"echo": message}

        assert len(gw._pending_tools) == 1
        tool = gw._pending_tools[0]
        assert tool.name == "echo"
        assert tool.description == "Echo a message back."
        assert tool.fn is echo

    def test_tool_decorator_with_parens(self) -> None:
        """@gw.tool() — decorator with empty parens."""
        gw = Gateway()

        @gw.tool()
        async def add_numbers(a: float, b: float) -> dict[str, Any]:
            """Add two numbers."""
            return {"result": a + b}

        assert len(gw._pending_tools) == 1
        tool = gw._pending_tools[0]
        assert tool.name == "add-numbers"  # underscores -> hyphens
        assert tool.description == "Add two numbers."

    def test_tool_decorator_custom_name(self) -> None:
        gw = Gateway()

        @gw.tool(name="my-custom-tool", description="Custom description")
        async def something(x: str) -> dict[str, Any]:
            return {"x": x}

        tool = gw._pending_tools[0]
        assert tool.name == "my-custom-tool"
        assert tool.description == "Custom description"

    def test_tool_decorator_explicit_parameters(self) -> None:
        gw = Gateway()
        params = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }

        @gw.tool(parameters=params)
        async def search(q: str) -> dict[str, Any]:
            """Search."""
            return {"q": q}

        tool = gw._pending_tools[0]
        assert tool.parameters_schema == params

    def test_tool_decorator_annotated_hints(self) -> None:
        gw = Gateway()

        @gw.tool()
        async def greet(
            name: Annotated[str, "Person's name"],
            age: Annotated[int, "Age"],
        ) -> dict[str, Any]:
            """Greet someone."""
            return {"name": name, "age": age}

        tool = gw._pending_tools[0]
        props = tool.parameters_schema["properties"]
        assert props["name"]["description"] == "Person's name"
        assert props["age"]["description"] == "Age"
        assert props["age"]["type"] == "integer"

    def test_tool_decorator_pydantic_model(self) -> None:
        gw = Gateway()

        @gw.tool()
        async def search(params: _ToolInput) -> dict[str, Any]:
            """Search with model."""
            return {}

        tool = gw._pending_tools[0]
        assert "query" in tool.parameters_schema["properties"]
        assert "limit" in tool.parameters_schema["properties"]

    def test_tool_decorator_allowed_agents(self) -> None:
        gw = Gateway()

        @gw.tool(allowed_agents=["admin"])
        async def dangerous(cmd: str) -> dict[str, Any]:
            """Restricted tool."""
            return {}

        tool = gw._pending_tools[0]
        assert tool.allowed_agents == ["admin"]

    def test_tool_decorator_require_approval(self) -> None:
        gw = Gateway()

        @gw.tool(require_approval=True)
        async def risky(action: str) -> dict[str, Any]:
            """Needs approval."""
            return {}

        tool = gw._pending_tools[0]
        assert tool.require_approval is True

    def test_multiple_tools(self) -> None:
        gw = Gateway()

        @gw.tool
        async def tool_a(x: str) -> dict[str, Any]:
            """A."""
            return {}

        @gw.tool()
        async def tool_b(y: int) -> dict[str, Any]:
            """B."""
            return {}

        assert len(gw._pending_tools) == 2
        assert gw._pending_tools[0].name == "tool-a"
        assert gw._pending_tools[1].name == "tool-b"

    def test_decorated_function_still_callable(self) -> None:
        """The decorated function should still work normally."""
        gw = Gateway()

        @gw.tool
        def echo(message: str) -> dict[str, str]:
            """Echo."""
            return {"echo": message}

        result = echo("hello")
        assert result == {"echo": "hello"}
