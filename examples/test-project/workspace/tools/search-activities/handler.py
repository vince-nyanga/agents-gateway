"""Mock activity search tool handler."""

from __future__ import annotations

from typing import Any


def handle(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return mock activity results."""
    destination = arguments.get("destination", "Unknown")
    date = arguments.get("date", "Unknown")
    return {
        "destination": destination,
        "date": date,
        "activities": [
            {"name": "City Walking Tour", "duration_hours": 3, "price_usd": 25},
            {"name": "Museum of Art Visit", "duration_hours": 2, "price_usd": 15},
            {"name": "River Cruise", "duration_hours": 1.5, "price_usd": 40},
            {"name": "Local Food Tasting", "duration_hours": 2.5, "price_usd": 55},
        ],
    }
