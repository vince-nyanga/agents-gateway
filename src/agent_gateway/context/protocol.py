"""Protocol for dynamic context retrieval."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ContextRetriever(Protocol):
    """Protocol for retrieving context at runtime.

    Implementers register named retrievers on the Gateway and agents
    reference them by name in AGENT.md frontmatter. Results are injected
    into the system prompt during prompt assembly.
    """

    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        """Retrieve context chunks relevant to the query for the given agent.

        Args:
            query: The user's message or query string.
            agent_id: The ID of the agent requesting context.

        Returns:
            A list of text chunks to inject into the system prompt.
        """
        ...

    async def initialize(self) -> None:
        """Called once during Gateway startup.

        Set up connections, load indices, warm caches, etc.
        """
        ...

    async def close(self) -> None:
        """Called during Gateway shutdown.

        Clean up connections, release resources, etc.
        """
        ...
