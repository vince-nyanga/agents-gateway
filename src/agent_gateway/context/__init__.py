"""Context retrieval for agents — static files and dynamic retrievers."""

from agent_gateway.context.protocol import ContextRetriever
from agent_gateway.context.registry import RetrieverRegistry

__all__ = ["ContextRetriever", "RetrieverRegistry"]
