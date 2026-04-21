"""Build per-agent typed invoke routes.

For each agent that declares ``input_schema`` or ``output_schema`` (via
AGENT.md frontmatter or ``gw.set_*_schema()``), this module produces a
dedicated ``APIRoute`` whose request/response bodies are concrete Pydantic
classes. The generic ``/v1/agents/{agent_id}/invoke`` route is still
registered for schemaless agents and for agents whose schema conversion
fails.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, create_model

# GatewayAPIRoute subclasses APIRoute; we return list[APIRoute] for ease of
# consumption by callers that mutate ``self.router.routes``.
from agent_gateway.api.errors import error_response
from agent_gateway.api.models import (
    InvokeOptions,
    InvokeRequest,
    InvokeResponse,
    ResultPayload,
)
from agent_gateway.api.openapi import build_responses
from agent_gateway.api.routes.base import GatewayAPIRoute
from agent_gateway.api.routes.invoke import _invoke_agent_core
from agent_gateway.api.schema_to_model import (
    jsonschema_to_pydantic,
    sanitize_agent_id,
)
from agent_gateway.auth.scopes import RequireScope
from agent_gateway.exceptions import ModelConversionError

if TYPE_CHECKING:
    from agent_gateway.workspace.agent import AgentDefinition
    from agent_gateway.workspace.loader import WorkspaceState

logger = logging.getLogger(__name__)


def _resolve_input_model(
    agent: AgentDefinition,
    py_id: str,
) -> type[BaseModel] | None:
    """Return a concrete input Pydantic class for the agent, or None.

    Prefers the programmatically-registered class
    (``agent._pydantic_input_model``) over a JSON Schema round-trip.
    """
    if agent._pydantic_input_model is not None:
        return agent._pydantic_input_model
    if agent.input_schema:
        try:
            return jsonschema_to_pydantic(agent.input_schema, f"AgentInput_{py_id}")
        except ModelConversionError as exc:
            logger.warning(
                "Failed to convert input_schema for agent '%s' to Pydantic "
                "model; falling back to generic route: %s",
                agent.id,
                exc,
            )
            return None
    return None


def _resolve_output_model(
    agent: AgentDefinition,
    py_id: str,
) -> type[BaseModel] | None:
    """Return a concrete output Pydantic class for the agent, or None."""
    if agent._pydantic_output_model is not None:
        return agent._pydantic_output_model
    if agent.output_schema:
        try:
            return jsonschema_to_pydantic(agent.output_schema, f"AgentOutput_{py_id}")
        except ModelConversionError as exc:
            logger.warning(
                "Failed to convert output_schema for agent '%s' to Pydantic "
                "model; falling back to generic route: %s",
                agent.id,
                exc,
            )
            return None
    return None


def _make_typed_handler(agent_id: str) -> Any:
    """Build the async handler for a per-agent route.

    The handler's body type is bound at route-registration time via the
    generated ``request_model`` / ``response_model`` on the ``APIRoute``.
    Inside, we take the validated body as a dict and delegate to
    ``_invoke_agent_core`` with ``skip_input_validation=True`` since
    FastAPI already validated the request.
    """

    async def _typed_invoke(
        body: Any,
        request: Request,
    ) -> InvokeResponse | JSONResponse:
        # body is an instance of the per-agent InvokeRequest subclass.
        try:
            payload = body.model_dump(by_alias=True)
        except AttributeError:
            return error_response(
                500,
                "invalid_body",
                "Typed invoke handler received a non-Pydantic body",
            )
        raw_input = payload.get("input") or {}
        input_: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
        raw_options = payload.get("options") or {}
        options = InvokeOptions.model_validate(
            raw_options if isinstance(raw_options, dict) else {}
        )
        message = payload.get("message", "")
        result = await _invoke_agent_core(
            gw=request.app,
            agent_id=agent_id,
            message=str(message),
            input_=input_,
            options=options,
            request=request,
            skip_input_validation=True,
        )
        # If the caller supplied an ad-hoc output_schema override, the
        # executed output will not match the agent-declared response_model
        # and FastAPI's response validation will raise. Detect that case
        # and short-circuit by returning a raw JSONResponse (FastAPI skips
        # response_model validation when the handler returns a Response).
        if options.output_schema is not None and isinstance(result, InvokeResponse):
            return JSONResponse(
                status_code=200,
                content=result.model_dump(mode="json"),
            )
        return result

    return _typed_invoke


def _build_envelope_models(
    agent_id: str,
    py_id: str,
    input_model: type[BaseModel] | None,
    output_model: type[BaseModel] | None,
) -> tuple[type[InvokeRequest], type[InvokeResponse]]:
    """Compose per-agent request/response wrappers over the shared envelopes."""
    if input_model is not None:
        request_cls = create_model(
            f"InvokeRequest_{py_id}",
            __base__=InvokeRequest,
            input=(input_model, ...),
        )
    else:
        # No input_schema — keep the generic request shape but emit a named
        # alias so OpenAPI shows the agent-specific operation clearly.
        request_cls = create_model(
            f"InvokeRequest_{py_id}",
            __base__=InvokeRequest,
        )

    if output_model is not None:
        result_cls = create_model(
            f"ResultPayload_{py_id}",
            __base__=ResultPayload,
            output=(output_model | None, None),
        )
        response_cls = create_model(
            f"InvokeResponse_{py_id}",
            __base__=InvokeResponse,
            result=(result_cls | None, None),
        )
    else:
        response_cls = create_model(
            f"InvokeResponse_{py_id}",
            __base__=InvokeResponse,
        )

    return request_cls, response_cls


def build_per_agent_invoke_routes(
    gw: Any,
    workspace: WorkspaceState,
) -> tuple[list[APIRoute], set[str]]:
    """Build typed invoke routes for every agent with a schema.

    Returns ``(routes, paths)``. ``paths`` is the set of Gateway-local
    paths used by the custom ``RequestValidationError`` handler so it can
    decide whether to apply the agent-gateway error envelope or defer to
    FastAPI's default.

    Agents whose conversion fails contribute no route; a warning is logged
    and they continue to be served by the generic parameterized route.
    """
    routes: list[APIRoute] = []
    paths: set[str] = set()

    for agent_id, agent in workspace.agents.items():
        has_input = agent.input_schema is not None or agent._pydantic_input_model is not None
        has_output = agent.output_schema is not None or agent._pydantic_output_model is not None
        if not has_input and not has_output:
            continue

        py_id = sanitize_agent_id(agent_id)
        input_model = _resolve_input_model(agent, py_id)
        output_model = _resolve_output_model(agent, py_id)

        # If both declared models failed to resolve, there's nothing to add
        # over the generic route.
        if not input_model and not output_model:
            logger.warning(
                "Agent '%s' declares schemas but no Pydantic models could be "
                "built; skipping per-agent route.",
                agent_id,
            )
            continue

        request_cls, response_cls = _build_envelope_models(
            agent_id, py_id, input_model, output_model
        )

        handler = _make_typed_handler(agent_id)
        # Rebind the body annotation so FastAPI treats the validated model
        # as the request schema.
        handler.__annotations__ = {
            "body": request_cls,
            "request": Request,
            "return": InvokeResponse | JSONResponse,
        }

        path = f"/v1/agents/{agent_id}/invoke"
        description = agent.description or f"Invoke the {agent_id} agent with typed input/output."
        route = GatewayAPIRoute(
            path=path,
            endpoint=handler,
            response_model=response_cls,
            methods=["POST"],
            name=f"invoke_agent__{agent_id}",
            summary=f"Invoke {agent_id}",
            description=description,
            tags=["Agents"],
            responses={
                202: {
                    "description": (
                        "Accepted — async execution queued. Poll via the returned URL."
                    ),
                },
                **build_responses(auth=True, not_found=True, rate_limit=True),
            },
            dependencies=[Depends(RequireScope("agents:invoke"))],
        )
        routes.append(route)
        paths.add(path)

    return routes, paths
