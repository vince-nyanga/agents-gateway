"""Assemble layered system prompts for agents."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from agent_gateway.context.protocol import ContextRetriever
from agent_gateway.context.registry import RetrieverRegistry
from agent_gateway.workspace.agent import AgentDefinition
from agent_gateway.workspace.loader import WorkspaceState
from agent_gateway.workspace.skill import SkillDefinition

logger = logging.getLogger(__name__)


async def assemble_system_prompt(
    agent: AgentDefinition,
    workspace: WorkspaceState,
    *,
    query: str = "",
    retriever_registry: RetrieverRegistry | None = None,
) -> str:
    """Build the full system prompt for an agent.

    Layer order:
    1. Root AGENTS.md (shared system context)
    2. Root BEHAVIOR.md (shared behavior/guardrails)
    3. Agent AGENT.md (agent-specific instructions)
    4. Agent BEHAVIOR.md (agent-specific behavior/guardrails)
    5. Static context files (reference material from context/ dir + frontmatter)
    6. Dynamic retriever results (fetched at prompt assembly time)
    7. Skill instructions (from each skill the agent uses)

    Note: Business context (gateway.yaml context block) is injected
    by the Gateway at invocation time, not during workspace loading.
    """
    parts: list[str] = []

    # 0. Current date/time
    now = datetime.now(UTC)
    parts.append(f"Current date and time (UTC): {now.strftime('%Y-%m-%d %H:%M')}")

    # 1. Root system prompt
    if workspace.root_system_prompt:
        parts.append(workspace.root_system_prompt)

    # 2. Root behavior
    if workspace.root_behavior_prompt:
        parts.append(workspace.root_behavior_prompt)

    # 3. Agent prompt
    parts.append(agent.agent_prompt)

    # 4. Agent behavior
    if agent.behavior_prompt:
        parts.append(agent.behavior_prompt)

    # 5. Static context files
    if agent.context_content:
        context_section = "## Reference Material\n\n" + "\n\n---\n\n".join(agent.context_content)
        parts.append(context_section)

    # 6. Dynamic retriever results
    if agent.retrievers and retriever_registry is not None and query:
        retrieved = await _fetch_retriever_context(
            agent=agent,
            query=query,
            registry=retriever_registry,
        )
        if retrieved:
            parts.append("## Retrieved Context\n\n" + "\n\n---\n\n".join(retrieved))

    # 7. Skill instructions
    resolved_skills = [
        skill for name in agent.skills if (skill := workspace.skills.get(name)) is not None
    ]
    if resolved_skills:
        skill_section = _format_skills_section(resolved_skills)
        parts.append(skill_section)

    return "\n\n---\n\n".join(parts)


_RETRIEVER_TIMEOUT_SECONDS = 10.0


async def _fetch_retriever_context(
    agent: AgentDefinition,
    query: str,
    registry: RetrieverRegistry,
) -> list[str]:
    """Call each retriever for the agent concurrently, collecting results.

    Each retriever is given a timeout of ``_RETRIEVER_TIMEOUT_SECONDS``.
    Failures and timeouts are logged and skipped — never crash the prompt assembly.
    """
    retrievers = registry.resolve_for_agent(agent.retrievers)
    if not retrievers:
        return []

    async def _call_one(retriever: ContextRetriever) -> list[str]:
        return await asyncio.wait_for(
            retriever.retrieve(query=query, agent_id=agent.id),
            timeout=_RETRIEVER_TIMEOUT_SECONDS,
        )

    settled = await asyncio.gather(
        *[_call_one(r) for r in retrievers],
        return_exceptions=True,
    )

    results: list[str] = []
    for outcome in settled:
        if isinstance(outcome, TimeoutError):
            logger.warning(
                "Retriever timed out for agent '%s' after %.1fs",
                agent.id,
                _RETRIEVER_TIMEOUT_SECONDS,
            )
        elif isinstance(outcome, BaseException):
            logger.warning(
                "Retriever failed for agent '%s'",
                agent.id,
                exc_info=outcome,
            )
        else:
            results.extend(outcome)
    return results


def _format_skills_section(skills: list[SkillDefinition]) -> str:
    """Format skill instructions for injection into the system prompt."""
    parts = ["## Available Skills\n"]
    for skill in skills:
        parts.append(f"### Skill: {skill.name}\n")
        if skill.description:
            parts.append(f"*{skill.description}*\n")
        if skill.instructions:
            parts.append(skill.instructions)
        parts.append("")
    return "\n".join(parts)
