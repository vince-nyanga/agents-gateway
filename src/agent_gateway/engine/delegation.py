"""Built-in delegation tool for agent-to-agent communication."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_gateway.gateway import Gateway

logger = logging.getLogger(__name__)

MAX_RESULT_BYTES = 32 * 1024  # 32KB truncation limit


async def run_delegation(
    gateway: Gateway,
    *,
    caller_agent_id: str,
    delegates_to: list[str],
    execution_id: str,
    root_execution_id: str,
    delegation_depth: int,
    user_id: str | None,
    # tool params
    agent_id: str,
    message: str,
    input: dict[str, Any] | None = None,
) -> str:
    """Execute delegation to another agent, return result string."""
    # Permission check
    if agent_id not in delegates_to:
        return (
            f"Error: Agent '{caller_agent_id}' is not allowed to delegate to '{agent_id}'. "
            f"Allowed targets: {delegates_to}"
        )

    # Depth check
    max_depth = gateway._config.guardrails.max_delegation_depth if gateway._config else 3
    if delegation_depth >= max_depth:
        return f"Error: Maximum delegation depth ({max_depth}) reached. Cannot delegate further."

    try:
        result = await gateway.invoke(
            agent_id=agent_id,
            message=message,
            input=input,
            parent_execution_id=execution_id,
            root_execution_id=root_execution_id,
            delegation_depth=delegation_depth + 1,
        )
        result_str = result.raw_text if result.raw_text else json.dumps(result.to_dict())
        if len(result_str.encode()) > MAX_RESULT_BYTES:
            result_str = (
                result_str.encode()[:MAX_RESULT_BYTES].decode(errors="ignore") + "... [truncated]"
            )
        return result_str
    except Exception as exc:
        logger.warning("Delegation to %s failed: %s", agent_id, exc)
        return f"Error: Delegation to '{agent_id}' failed: {exc}"
