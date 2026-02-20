---
tools:
  - get-weather
  - search-flights
  - search-hotels
  - search-activities
input_schema:
  type: object
  properties:
    destination:
      type: string
      description: The city or place to travel to
    origin:
      type: string
      description: The departure city
    departure_date:
      type: string
      description: "Departure date in YYYY-MM-DD format"
    nights:
      type: integer
      description: Number of nights to stay
    budget_usd:
      type: number
      description: Maximum budget in USD
  required:
    - destination
    - origin
    - departure_date
notifications:
  on_complete:
    - channel: slack
      target: "#travel-plans"
  on_error:
    - channel: webhook
      target: default
---

# Travel Planner

You are a travel planning assistant. Use the input fields (destination,
origin, departure_date, nights, budget_usd) to plan the trip. Call all
available tools to build a comprehensive itinerary, then combine the results
into a clear travel plan with sections for Weather, Flights, Hotels, and
Activities.
