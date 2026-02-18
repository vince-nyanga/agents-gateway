---
name: search-hotels
description: Search for available hotels at a destination for given dates.
parameters:
  destination:
    type: string
    description: "The city to search hotels in"
    required: true
  checkin:
    type: string
    description: "Check-in date (YYYY-MM-DD)"
    required: true
  checkout:
    type: string
    description: "Check-out date (YYYY-MM-DD)"
    required: true
---

# Search Hotels Tool

Returns mock hotel search results.
