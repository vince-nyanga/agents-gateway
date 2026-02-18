"""HTTP example tool handler — makes GET requests."""

from __future__ import annotations

from typing import Any
from urllib.request import urlopen


def handle(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    """Fetch a URL and return the response body."""
    url = arguments["url"]
    with urlopen(url, timeout=10) as resp:  # noqa: S310
        body = resp.read().decode("utf-8", errors="replace")
    return {"status": resp.status, "body": body[:2000]}
