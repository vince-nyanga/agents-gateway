"""Tests for input context validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agent_gateway.engine.input import (
    resolve_input_schema,
    validate_input,
    validate_input_pydantic,
)

SIMPLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "deal_id": {"type": "string"},
        "amount": {"type": "number"},
    },
    "required": ["deal_id"],
}


class DealInput(BaseModel):
    deal_id: str
    amount: float = 0.0
    tier: str = "standard"


# -- resolve_input_schema -----------------------------------------------------


class TestResolveInputSchema:
    def test_dict_passthrough(self) -> None:
        json_schema, model_cls = resolve_input_schema(SIMPLE_SCHEMA)
        assert json_schema is SIMPLE_SCHEMA
        assert model_cls is None

    def test_pydantic_model(self) -> None:
        json_schema, model_cls = resolve_input_schema(DealInput)
        assert model_cls is DealInput
        assert json_schema["type"] == "object"
        assert "deal_id" in json_schema["properties"]
        assert "amount" in json_schema["properties"]


# -- validate_input (JSON Schema) --------------------------------------------


class TestValidateInput:
    def test_valid_context(self) -> None:
        errors = validate_input({"deal_id": "D-123", "amount": 50000}, SIMPLE_SCHEMA)
        assert errors == []

    def test_valid_context_optional_missing(self) -> None:
        errors = validate_input({"deal_id": "D-123"}, SIMPLE_SCHEMA)
        assert errors == []

    def test_missing_required_field(self) -> None:
        errors = validate_input({"amount": 100}, SIMPLE_SCHEMA)
        assert len(errors) == 1
        assert "deal_id" in errors[0]

    def test_wrong_type(self) -> None:
        errors = validate_input({"deal_id": 123}, SIMPLE_SCHEMA)
        assert len(errors) == 1

    def test_empty_context_with_required(self) -> None:
        errors = validate_input({}, SIMPLE_SCHEMA)
        assert len(errors) == 1
        assert "deal_id" in errors[0]

    def test_none_context_with_required(self) -> None:
        errors = validate_input(None, SIMPLE_SCHEMA)
        assert len(errors) == 1
        assert "deal_id" in errors[0]

    def test_none_context_no_required(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"note": {"type": "string"}},
        }
        errors = validate_input(None, schema)
        assert errors == []

    def test_empty_context_no_required(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"note": {"type": "string"}},
        }
        errors = validate_input({}, schema)
        assert errors == []

    def test_extra_fields_allowed_by_default(self) -> None:
        errors = validate_input(
            {"deal_id": "D-1", "extra": "field"},
            SIMPLE_SCHEMA,
        )
        assert errors == []


# -- validate_input_pydantic --------------------------------------------------


class TestValidateInputPydantic:
    def test_valid_context(self) -> None:
        errors = validate_input_pydantic({"deal_id": "D-1", "amount": 100.0}, DealInput)
        assert errors == []

    def test_missing_required(self) -> None:
        errors = validate_input_pydantic({"amount": 100.0}, DealInput)
        assert len(errors) >= 1

    def test_wrong_type(self) -> None:
        errors = validate_input_pydantic({"deal_id": 123}, DealInput)
        assert len(errors) >= 1

    def test_none_context_with_required(self) -> None:
        errors = validate_input_pydantic(None, DealInput)
        assert len(errors) >= 1

    def test_empty_context_with_required(self) -> None:
        errors = validate_input_pydantic({}, DealInput)
        assert len(errors) >= 1

    def test_defaults_applied(self) -> None:
        errors = validate_input_pydantic({"deal_id": "D-1"}, DealInput)
        assert errors == []
