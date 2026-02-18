"""Tests for JSON Schema generation from function signatures."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel

from agent_gateway.workspace.schema import schema_from_function


class _SearchParams(BaseModel):
    """Module-level Pydantic model for testing."""

    query: str
    limit: int = 10


class TestBareTypeHints:
    def test_str_param(self) -> None:
        def fn(message: str) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert schema["type"] == "object"
        assert schema["properties"]["message"]["type"] == "string"
        assert schema["required"] == ["message"]

    def test_int_param(self) -> None:
        def fn(count: int) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert schema["properties"]["count"]["type"] == "integer"

    def test_float_param(self) -> None:
        def fn(price: float) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert schema["properties"]["price"]["type"] == "number"

    def test_bool_param(self) -> None:
        def fn(active: bool) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert schema["properties"]["active"]["type"] == "boolean"

    def test_list_param(self) -> None:
        def fn(items: list[str]) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert schema["properties"]["items"]["type"] == "array"
        assert schema["properties"]["items"]["items"]["type"] == "string"

    def test_optional_param_not_required(self) -> None:
        def fn(name: str, tag: str = "default") -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert schema["required"] == ["name"]
        assert "tag" in schema["properties"]

    def test_no_type_hint_defaults_to_string(self) -> None:
        def fn(x):  # type: ignore[no-untyped-def]
            ...

        schema = schema_from_function(fn)
        assert schema["properties"]["x"]["type"] == "string"

    def test_multiple_params(self) -> None:
        def fn(a: float, b: float) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert len(schema["properties"]) == 2
        assert schema["required"] == ["a", "b"]

    def test_no_required_when_all_have_defaults(self) -> None:
        def fn(x: str = "hi", y: int = 5) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert "required" not in schema


class TestAnnotatedHints:
    def test_annotated_with_description(self) -> None:
        def fn(message: Annotated[str, "The message to send"]) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        prop = schema["properties"]["message"]
        assert prop["type"] == "string"
        assert prop["description"] == "The message to send"

    def test_annotated_int(self) -> None:
        def fn(count: Annotated[int, "Number of items"]) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        prop = schema["properties"]["count"]
        assert prop["type"] == "integer"
        assert prop["description"] == "Number of items"

    def test_annotated_no_string_falls_back_to_name(self) -> None:
        def fn(count: Annotated[int, 42]) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        prop = schema["properties"]["count"]
        assert prop["description"] == "count"


class TestPydanticModel:
    def test_pydantic_model_parameter(self) -> None:
        def fn(params: _SearchParams) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert "properties" in schema
        assert "query" in schema["properties"]
        assert "limit" in schema["properties"]
        assert "required" in schema
        assert "query" in schema["required"]


class TestLiteralEnum:
    def test_literal_creates_enum(self) -> None:
        def fn(color: Literal["red", "green", "blue"]) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        prop = schema["properties"]["color"]
        assert prop["type"] == "string"
        assert prop["enum"] == ["red", "green", "blue"]


class TestOptionalType:
    def test_optional_type(self) -> None:
        def fn(name: str | None = None) -> dict:  # type: ignore[type-arg]
            ...

        schema = schema_from_function(fn)
        assert schema["properties"]["name"]["type"] == "string"
        assert "required" not in schema


class TestSelfClsSkipped:
    def test_self_skipped(self) -> None:
        class Foo:
            def method(self, msg: str) -> dict:  # type: ignore[type-arg]
                ...

        schema = schema_from_function(Foo.method)
        assert "self" not in schema["properties"]
        assert "msg" in schema["properties"]
