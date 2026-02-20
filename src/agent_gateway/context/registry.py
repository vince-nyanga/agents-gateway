"""Registry for named context retrievers."""

from __future__ import annotations

import logging

from agent_gateway.context.protocol import ContextRetriever

logger = logging.getLogger(__name__)


class RetrieverRegistry:
    """Maps retriever names to instances and resolves them for agents."""

    def __init__(self) -> None:
        self._retrievers: dict[str, ContextRetriever] = {}

    def register(self, name: str, retriever: ContextRetriever) -> None:
        """Register a named retriever.

        Raises ValueError if a retriever with the same name is already registered.
        """
        if name in self._retrievers:
            raise ValueError(f"Retriever '{name}' is already registered")
        self._retrievers[name] = retriever

    def resolve_for_agent(self, retriever_names: list[str]) -> list[ContextRetriever]:
        """Resolve retriever instances for the given names.

        Unknown names are skipped with a warning.
        """
        resolved: list[ContextRetriever] = []
        for name in retriever_names:
            retriever = self._retrievers.get(name)
            if retriever is None:
                logger.warning("Unknown retriever '%s', skipping", name)
                continue
            resolved.append(retriever)
        return resolved

    async def initialize_all(self) -> None:
        """Call initialize() on all registered retrievers."""
        for name, retriever in self._retrievers.items():
            try:
                await retriever.initialize()
            except Exception:
                logger.warning("Failed to initialize retriever '%s'", name, exc_info=True)

    async def close_all(self) -> None:
        """Call close() on all registered retrievers."""
        for name, retriever in self._retrievers.items():
            try:
                await retriever.close()
            except Exception:
                logger.warning("Failed to close retriever '%s'", name, exc_info=True)
