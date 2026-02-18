"""Generate JSON Schema from Python function signatures for LLM tool declarations."""

from __future__ import annotations

import inspect
from typing import Annotated, Any, Literal, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel

# Python type -> JSON Schema type mapping
TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def schema_from_function(fn: Any) -> dict[str, Any]:
    """Generate JSON Schema parameters from a function's type hints.

    Supports 4 modes:
    1. Single Pydantic model parameter -> model.model_json_schema()
    2. Annotated[type, "description"] parameters -> type + description extracted
    3. Bare type hints -> type inferred, parameter name used as description
    4. No hints -> all params treated as string
    """
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        # Fallback: use raw annotations when get_type_hints fails
        # (e.g., locally-defined classes with `from __future__ import annotations`)
        hints = _get_raw_annotations(fn)
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls", "return"):
            continue

        hint = hints.get(name, str)

        # Check if single Pydantic model parameter
        if inspect.isclass(hint) and issubclass(hint, BaseModel):
            return hint.model_json_schema()

        prop = _hint_to_schema(hint, name)
        properties[name] = prop

        # Required if no default
        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _hint_to_schema(hint: Any, name: str) -> dict[str, Any]:
    """Convert a single type hint to a JSON Schema property."""
    origin = get_origin(hint)
    args = get_args(hint)

    # Annotated[type, "description"]
    if origin is Annotated:
        base_type = args[0]
        description = next((a for a in args[1:] if isinstance(a, str)), name)
        prop = _base_type_to_schema(base_type)
        prop["description"] = description
        return prop

    # Optional[X] is Union[X, None]
    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            prop = _base_type_to_schema(non_none[0])
            prop["description"] = name
            return prop

    # Literal["A", "B"] -> enum
    if origin is Literal:
        return {"type": "string", "enum": list(args), "description": name}

    # list[X]
    if origin is list and args:
        item_schema = _base_type_to_schema(args[0])
        return {"type": "array", "items": item_schema, "description": name}

    # Plain type
    prop = _base_type_to_schema(hint)
    prop["description"] = name
    return prop


def _base_type_to_schema(t: Any) -> dict[str, Any]:
    """Map a Python type to JSON Schema."""
    json_type = TYPE_MAP.get(t, "string")
    return {"type": json_type}


def _get_raw_annotations(fn: Any) -> dict[str, Any]:
    """Extract raw annotations, evaluating string annotations against the function's globals."""
    raw = getattr(fn, "__annotations__", {})
    globalns = getattr(fn, "__globals__", {})
    hints: dict[str, Any] = {}
    for name, annotation in raw.items():
        if isinstance(annotation, str):
            try:
                hints[name] = eval(annotation, globalns)  # noqa: S307
            except Exception:
                hints[name] = str
        else:
            hints[name] = annotation
    return hints
