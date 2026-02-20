"""Shared context retrievers for example project."""

from __future__ import annotations


class EmailHistoryRetriever:
    """Example ContextRetriever that returns recent email thread context.

    In production this could query a vector database, email API, or search index.
    Here we simulate it with a static lookup for demonstration.
    """

    THREADS: dict[str, list[str]] = {
        "onboarding": [
            "Thread with Marcus (Feb 18): Discussed webhook delivery guarantees. "
            "Marcus needs SLA numbers by Friday.",
            "Thread with Priya (Feb 19): Confirmed API rate limits are 1000 req/min. "
            "Will share updated docs tomorrow.",
        ],
        "project": [
            "Thread with Sarah (Feb 17): Q1 planning session scheduled for Thursday. "
            "Need to finalize budget numbers.",
            "Thread with Team (Feb 18): Design mockups approved. Moving to "
            "engineering sprint next week.",
        ],
    }

    async def retrieve(self, *, query: str, agent_id: str) -> list[str]:
        """Return email threads relevant to the query."""
        results: list[str] = []
        query_lower = query.lower()
        for topic, threads in self.THREADS.items():
            if topic in query_lower or any(word in query_lower for word in topic.split()):
                results.extend(threads)
        # If no specific match, return most recent threads as general context
        if not results:
            for threads in self.THREADS.values():
                results.extend(threads[:1])
        return results

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass
