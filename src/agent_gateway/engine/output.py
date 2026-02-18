"""Structured output validation — parse and validate LLM output against JSON Schema."""

from __future__ import annotations

import json
import logging
from typing import Any

import jsonschema

logger = logging.getLogger(__name__)

CORRECTION_PROMPT = (
    "Your response did not match the required JSON schema.\n"
    "Errors: {errors}\n\n"
    "Please respond again with valid JSON matching this schema:\n"
    "```json\n{schema}\n```"
)

SCHEMA_INSTRUCTION = (
    "\n\n## Required Output Format\n\n"
    "You MUST respond with valid JSON matching this schema:\n"
    "```json\n{schema}\n```\n"
    "Do not include any other text outside the JSON object."
)


def build_schema_instruction(schema: dict[str, Any]) -> str:
    """Build the schema instruction to append to the system prompt."""
    return SCHEMA_INSTRUCTION.format(schema=json.dumps(schema, indent=2))


def validate_output(
    raw_text: str,
    schema: dict[str, Any],
) -> tuple[Any | None, list[str]]:
    """Validate raw LLM output against a JSON Schema.

    Returns:
        (parsed_output, errors) — parsed_output is None if validation fails.
    """
    # Try to parse JSON
    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as e:
        return None, [f"Invalid JSON: {e}"]

    # Validate against schema
    try:
        jsonschema.validate(instance=parsed, schema=schema)
    except jsonschema.ValidationError as e:
        return None, [e.message]

    return parsed, []


def build_correction_message(
    errors: list[str],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Build a correction prompt message for the LLM to retry."""
    return {
        "role": "user",
        "content": CORRECTION_PROMPT.format(
            errors="; ".join(errors),
            schema=json.dumps(schema, indent=2),
        ),
    }
