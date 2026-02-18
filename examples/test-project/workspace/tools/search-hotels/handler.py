"""Mock hotel search tool handler."""

from __future__ import annotations

from typing import Any


def handle(arguments: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return mock hotel results."""
    destination = arguments.get("destination", "Unknown")
    checkin = arguments.get("checkin", "Unknown")
    checkout = arguments.get("checkout", "Unknown")
    return {
        "destination": destination,
        "checkin": checkin,
        "checkout": checkout,
        "hotels": [
            {"name": "Grand Plaza Hotel", "stars": 4, "price_per_night_usd": 150},
            {"name": "Budget Inn Express", "stars": 2, "price_per_night_usd": 65},
            {"name": "Riverside Boutique", "stars": 5, "price_per_night_usd": 280},
        ],
    }
