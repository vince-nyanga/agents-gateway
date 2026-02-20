"""Agent Gateway - an opinionated FastAPI extension for AI agent services."""

__version__ = "0.0.0"  # Replaced at build time by GitVersion

from agent_gateway.context.protocol import ContextRetriever
from agent_gateway.gateway import Gateway

__all__ = ["ContextRetriever", "Gateway", "__version__"]
