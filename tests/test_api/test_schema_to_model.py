"""Unit tests for JSON Schema -> Pydantic model conversion."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agent_gateway.api.schema_to_model import (
    jsonschema_to_pydantic,
    sanitize_agent_id,
)
from agent_gateway.exceptions import ModelConversionError


class TestSanitizeAgentId:
    def test_hyphen_replaced_with_underscore(self) -> None:
        assert sanitize_agent_id("data-analyst") == "data_analyst"

    def test_already_valid(self) -> None:
        assert sanitize_agent_id("foo_bar") == "foo_bar"

    def test_leading_digit_gets_prefix(self) -> None:
        assert sanitize_agent_id("123foo") == "_123foo"

    def test_punctuation_replaced(self) -> None:
        assert sanitize_agent_id("foo.bar!baz") == "foo_bar_baz"

    def test_empty_gets_underscore(self) -> None:
        # Empty input is sanitized to "_" (starts non-digit).
        assert sanitize_agent_id("") == "_"


class TestJsonSchemaToPydantic:
    def test_simple_object_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer", "minimum": 0},
            },
            "required": ["name"],
        }
        cls = jsonschema_to_pydantic(schema, "AgentInput_foo")
        assert issubclass(cls, BaseModel)
        assert cls.__name__ == "AgentInput_foo"
        assert "name" in cls.model_fields
        assert "count" in cls.model_fields

        # Valid instance
        inst = cls(name="alice", count=5)
        assert inst.model_dump() == {"name": "alice", "count": 5}

        # Missing required field
        with pytest.raises(ValidationError):
            cls(count=5)

    def test_schema_with_ref_and_nested(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "item": {"$ref": "#/$defs/Item"},
                "count": {"type": "integer"},
            },
            "required": ["item"],
            "$defs": {
                "Item": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                }
            },
        }
        cls = jsonschema_to_pydantic(schema, "AgentInput_ref")
        inst = cls(item={"id": "abc"}, count=1)
        data = inst.model_dump()
        assert data["item"]["id"] == "abc"

    def test_schema_with_array(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["items"],
        }
        cls = jsonschema_to_pydantic(schema, "AgentInput_arr")
        inst = cls(items=["a", "b", "c"])
        assert inst.model_dump() == {"items": ["a", "b", "c"]}

    def test_invalid_schema_raises_model_conversion_error(self) -> None:
        # Circular dict that won't JSON-serialise
        bad: dict = {}
        bad["self"] = bad
        with pytest.raises(ModelConversionError):
            jsonschema_to_pydantic(bad, "Bad")

    def test_generated_model_round_trips(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        }
        cls = jsonschema_to_pydantic(schema, "AgentInput_rt")
        data = {"name": "x", "tags": ["a", "b"]}
        inst = cls(**data)
        assert inst.model_dump() == data

    def test_class_name_is_applied(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        cls = jsonschema_to_pydantic(schema, "AgentInput_unique_name")
        assert cls.__name__ == "AgentInput_unique_name"
