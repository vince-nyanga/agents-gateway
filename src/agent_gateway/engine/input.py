"""Input validation — validate caller-provided input against agent input schemas."""

from __future__ import annotations

import logging
from typing import Any

import jsonschema
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


def resolve_input_schema(
    schema: dict[str, Any] | type[BaseModel],
) -> tuple[dict[str, Any], type[BaseModel] | None]:
    """Normalize an input schema to (json_schema_dict, optional model class).

    If *schema* is a Pydantic model class, the JSON Schema is generated
    automatically and the class is returned for later validation.
    If it's already a raw dict, it's passed through unchanged.
    """
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema(), schema
    return schema, None


def validate_input(
    input_data: dict[str, Any] | None,
    schema: dict[str, Any],
) -> list[str]:
    """Validate input against a JSON Schema.

    Returns:
        List of error messages. Empty list means validation passed.
    """
    # Treat None as empty object — if schema has required fields, this will fail
    instance = input_data if input_data is not None else {}

    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as e:
        return [e.message]

    return []


def validate_input_pydantic(
    input_data: dict[str, Any] | None,
    model_cls: type[BaseModel],
) -> list[str]:
    """Validate input against a Pydantic model.

    Returns:
        List of error messages. Empty list means validation passed.
    """
    instance = input_data if input_data is not None else {}

    try:
        model_cls.model_validate(instance)
        return []
    except ValidationError as e:
        return [err["msg"] for err in e.errors()]
