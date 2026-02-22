# Dashboard Revamp Plan

This document outlines the plan to revamp the Agent Gateway dashboard to match the modern design from the `agents-gateway` Stitch MCP project. The dashboard will continue to use FastAPI, Jinja2, and HTMX as its core technology stack.

## User Review Required

Please review this plan. The UI implementation will heavily rely on updating existing Jinja templates and CSS tokens to match the modern Stitch designs while preserving the HTMX-driven interaction model.
Let me know if there are specific new backend features you want prioritized.

## Proposed Changes

### 1. Global Layout & Styling
We will update the core styling and layout templates to match the new design system. **We will stick to Vanilla CSS (using CSS variables in `tokens.css`) and avoid any external CSS frameworks like Tailwind or Bootstrap**, to keep the stack simple and maintainable while achieving the premium, rich aesthetics of the Stitch designs.

#### [MODIFY] `src/agent_gateway/dashboard/static/dashboard/tokens.css`
Update CSS variables, color palettes (Light/Dark mode), typography (Inter font), and spacing to match the Stitch design themes.
#### [MODIFY] `src/agent_gateway/dashboard/static/dashboard/app.css`
Update component-level styles (buttons, cards, inputs, tables, sidebars) to reflect the new UI components.
#### [MODIFY] `src/agent_gateway/dashboard/templates/dashboard/base.html`
Update the overall layout structure, sidebar navigation icons, top bar layout, and theme toggles to match the "Agent Gateway Dashboard" and "Dashboard (Light Mode)" screens.

### 2. Page Templates Update (Jinja & HTMX)
We will revamp each page's template to match its corresponding Stitch screen while keeping HTMX attributes for interactivity.

#### [MODIFY] `src/agent_gateway/dashboard/templates/dashboard/agents.html` & `_agent_cards.html`
Match the "Agents Management" and "Agents (Light Mode)" screens. Update the grid layout and card designs for the agents.

#### [MODIFY] `src/agent_gateway/dashboard/templates/dashboard/chat.html`
Match the "Agent Chat" and "Agent Chat (Light Mode)" screens. Update the chat interface, message bubbles, and input area.

#### [MODIFY] `src/agent_gateway/dashboard/templates/dashboard/executions.html` & `_exec_rows.html`
Match the "Execution History" and "Executions (Light Mode)" screens. Update the table design, status badges, and pagination controls.

#### [MODIFY] `src/agent_gateway/dashboard/templates/dashboard/execution_detail.html` & `_trace_steps.html`
Match the "Execution Trace with Retry" screen. Implement the detailed trace view, error highlighting, and retry button UI. **Backend requirement:** Ensure the `/executions/{id}/retry` endpoint exists or add it if missing.

#### [MODIFY] `src/agent_gateway/dashboard/templates/dashboard/schedules.html`
Match the "Schedules & Cronjobs" and "Intuitive Schedule Creator" screens. Update the schedule list view and create a more intuitive modal/form for adding/editing cronjobs.

#### [MODIFY] `src/agent_gateway/dashboard/templates/dashboard/analytics.html`
Match the "System Analytics" and "Analytics (Light Mode)" screens. Update charts and metric cards.

### 3. Backend Enhancements
- Review current routes in `src/agent_gateway/dashboard/router.py`.
- Ensure data provided to templates matches the new UI requirements.
- Specifically, check if the "Execution Trace with Retry" requires a POST endpoint to re-trigger an execution if it doesn't already exist.
- Ensure the "Intuitive Schedule Creator" form fields match the existing `POST /schedules` schema, or update the backend schema if the UI introduces new configuration options.

## Verification Plan

### Automated Tests
- Run `pytest tests/` to ensure no existing dashboard or gateway functionality breaks.
- (If new endpoints are added) Add corresponding unit tests in `tests/test_dashboard/`.

### Manual Verification
- Start the server (`make run` or `uvicorn`).
- Navigate to `http://localhost:8000/dashboard/`.
- Visually verify each page aligns with the corresponding Stitch screen (in both Light and Dark mode).
- Click through all HTMX interactions (chat streaming, pagination, filtering) to ensure no interactivity is lost.
