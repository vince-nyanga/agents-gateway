"""JSON Schema -> Pydantic model conversion.

Used by per-agent typed invoke routes so Swagger / OpenAPI expose concrete
request and response shapes. Delegates to ``datamodel-code-generator`` which
handles ``$ref``, ``oneOf``, discriminators, recursive refs, and the other
JSON Schema features a hand-rolled walker would miss.

Conversion is a one-shot, cached in memory by the caller (per agent). Cost
is ~50-150ms per agent at startup; agents without schemas pay nothing.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import pathlib
import re
import tempfile
import uuid
from typing import Any

from pydantic import BaseModel

from agent_gateway.exceptions import ModelConversionError

logger = logging.getLogger(__name__)


def sanitize_agent_id(agent_id: str) -> str:
    """Convert an agent id into a valid Python identifier fragment.

    Agent ids may contain ``-`` which is not legal in Python class names.
    We replace ``-`` with ``_`` and strip any other non-identifier characters.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", agent_id)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def jsonschema_to_pydantic(
    schema: dict[str, Any],
    class_name: str,
) -> type[BaseModel]:
    """Generate a Pydantic v2 model class from a JSON Schema dict.

    Args:
        schema: A valid JSON Schema (Draft 2020-12 compatible).
        class_name: Name for the generated root class. Callers should prefix
            with the agent id to avoid collisions in ``components.schemas``.

    Returns:
        A Pydantic ``BaseModel`` subclass mirroring the schema.

    Raises:
        ModelConversionError: If ``datamodel-code-generator`` fails, the
            generated source cannot be imported, or the expected root class
            is not produced. Callers are expected to catch this and fall
            back to an untyped route.
    """
    try:
        from datamodel_code_generator import (  # type: ignore[attr-defined]
            DataModelType,
            InputFileType,
            PythonVersion,
            generate,
        )
    except ImportError as exc:  # pragma: no cover - hard dependency
        raise ModelConversionError(
            "datamodel-code-generator is not installed; "
            "add the dependency via 'uv add datamodel-code-generator>=0.26'"
        ) from exc

    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        input_path = td_path / "schema.json"
        output_path = td_path / "model.py"
        try:
            input_path.write_text(json.dumps(schema))
        except (TypeError, ValueError) as exc:
            raise ModelConversionError(f"schema is not JSON-serialisable: {exc}") from exc

        try:
            generate(
                input_=input_path,
                input_file_type=InputFileType.JsonSchema,
                output=output_path,
                output_model_type=DataModelType.PydanticV2BaseModel,
                target_python_version=PythonVersion.PY_311,
                class_name=class_name,
                use_standard_collections=True,
                use_annotated=True,
                field_constraints=True,
            )
        except Exception as exc:  # generator raises a grab-bag of errors
            raise ModelConversionError(f"datamodel-code-generator failed: {exc}") from exc

        if not output_path.exists():
            raise ModelConversionError("datamodel-code-generator produced no output")

        source = output_path.read_text()

        # Import the generated module in a uniquely-named namespace so
        # concurrent conversions never alias the same module object.
        mod_name = f"_ag_dyn_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(mod_name, output_path)
        if spec is None or spec.loader is None:
            raise ModelConversionError("failed to construct import spec for generated model")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise ModelConversionError(f"generated model module failed to import: {exc}") from exc

        # Generated code uses ``from __future__ import annotations``, which
        # makes all field annotations strings. Pydantic needs them resolved
        # against the module's globals before validators will work.
        namespace = dict(vars(module))
        for _name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
                try:
                    obj.model_rebuild(_types_namespace=namespace)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ModelConversionError(
                        f"Pydantic model_rebuild failed for {obj.__name__}: {exc}"
                    ) from exc

        # datamodel-code-generator normalises class names: it strips
        # underscores and applies PascalCase (``AgentInput_foo`` ->
        # ``AgentInputFoo``), and suffixes with ``Model`` when a schema
        # definition collides with the requested name. Pick the best match.
        candidates = [
            class_name,
            re.sub(r"_([a-z0-9])", lambda m: m.group(1).upper(), class_name),
            f"{class_name}Model",
        ]
        pascal = re.sub(r"_([a-zA-Z0-9])", lambda m: m.group(1).upper(), class_name)
        candidates.extend([pascal, f"{pascal}Model"])
        root: type[BaseModel] | None = None
        for name in candidates:
            candidate = getattr(module, name, None)
            if (
                candidate is not None
                and inspect.isclass(candidate)
                and issubclass(candidate, BaseModel)
                and candidate is not BaseModel
            ):
                root = candidate
                break

        if root is None:
            # Fall back to the last defined BaseModel subclass in the module
            # (datamodel-code-generator emits the root class last).
            all_models = [
                obj
                for _name, obj in inspect.getmembers(module)
                if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel
            ]
            if all_models:
                # Pick the class actually defined in this module (exclude
                # imports) by checking the __module__ attribute.
                module_locals = [m for m in all_models if m.__module__ == mod_name]
                if module_locals:
                    root = module_locals[-1]

        if root is None:
            logger.debug(
                "Generated source for missing root %s:\n%s",
                class_name,
                source,
            )
            raise ModelConversionError(
                f"generated module has no suitable BaseModel subclass (tried {candidates!r})"
            )

        # Rename to the requested class name so OpenAPI schemas use the
        # agent-prefixed name rather than the generator's default.
        root.__name__ = class_name
        root.__qualname__ = class_name
        return root
