"""Example MCP server using FastMCP for testing MCP integration.

Run standalone:
    uv run python mcp_test_server.py

Or let agent-gateway connect to it via stdio transport.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

server = FastMCP("test-tools")


@server.tool()
def current_time() -> str:
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


@server.tool()
def word_count(text: str) -> dict:
    """Count words, characters, and lines in the given text."""
    lines = text.splitlines()
    words = text.split()
    return {
        "characters": len(text),
        "words": len(words),
        "lines": len(lines),
    }


@server.tool()
def reverse_string(text: str) -> str:
    """Reverse a string - useful for testing MCP tool execution."""
    return text[::-1]


if __name__ == "__main__":
    server.run(transport="stdio")
