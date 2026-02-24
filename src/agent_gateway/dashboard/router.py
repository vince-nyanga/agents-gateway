"""Dashboard routes — Jinja2 + HTMX server-rendered UI."""

from __future__ import annotations

import importlib.resources
import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.responses import StreamingResponse

from agent_gateway.dashboard.auth import (
    DashboardUser,
    make_get_dashboard_user,
    make_login_handler,
    make_require_admin,
)
from agent_gateway.dashboard.models import (
    AgentCard,
    AnalyticsSummary,
    ConversationDetail,
    ConversationSummaryRow,
    ExecutionDetail,
    ExecutionRow,
    format_cost,
    format_datetime,
    format_duration,
    relative_time,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agent_gateway.config import DashboardConfig, DashboardOAuth2Config
    from agent_gateway.dashboard.oauth2 import OIDCDiscoveryClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20


def _build_templates(dash_config: DashboardConfig) -> Jinja2Templates:
    env = Environment(
        loader=PackageLoader("agent_gateway.dashboard"),
        autoescape=select_autoescape(["html"]),
    )
    # Global helpers available in all templates
    env.globals["format_cost"] = format_cost
    env.globals["format_datetime"] = format_datetime
    env.globals["format_duration"] = format_duration
    env.globals["relative_time"] = relative_time
    env.globals["json_dumps"] = json.dumps
    env.globals["dashboard_title"] = dash_config.title
    env.globals["dashboard_logo_url"] = dash_config.logo_url
    env.globals["dashboard_favicon_url"] = dash_config.favicon_url
    colors = dash_config.theme.resolved_colors()
    env.globals["dashboard_colors"] = colors
    # Legacy compat
    env.globals["dashboard_accent"] = colors.accent
    env.globals["dashboard_accent_dark"] = colors.accent_dark
    env.globals["dashboard_theme_mode"] = dash_config.theme.mode
    return Jinja2Templates(env=env)


def _static_dir() -> str:
    ref = importlib.resources.files("agent_gateway.dashboard") / "static"
    with importlib.resources.as_file(ref) as p:
        return str(p)


def register_dashboard(
    app: FastAPI,
    dash_config: DashboardConfig,
    oauth2_config: DashboardOAuth2Config | None = None,
    discovery_client: OIDCDiscoveryClient | None = None,
) -> None:
    """Mount dashboard routes and static files onto the FastAPI app."""
    auth_method = "oauth2" if oauth2_config else "password"
    templates = _build_templates(dash_config)
    templates.env.globals["auth_method"] = auth_method
    templates.env.globals["login_button_text"] = dash_config.auth.login_button_text
    get_dashboard_user = make_get_dashboard_user(dash_config.auth)
    require_admin = make_require_admin(dash_config.auth)
    login_handler = make_login_handler(dash_config.auth)

    # Static files
    try:
        static_path = _static_dir()
        app.mount(
            "/dashboard/static",
            StaticFiles(directory=static_path),
            name="dashboard-static",
        )
    except Exception:
        logger.warning("Dashboard static files not found; static assets may be missing")

    # Warn if admin credentials are partially configured
    auth_config = dash_config.auth
    has_user = auth_config.admin_username is not None
    has_pass = auth_config.admin_password is not None
    if has_user != has_pass:
        missing = "admin_password" if has_user else "admin_username"
        logger.warning(
            "Dashboard admin credentials are partially configured: %s is not set. "
            "Admin login will not work until both admin_username and admin_password are provided.",
            missing,
        )

    # --- Public router (no auth) ---
    public = APIRouter(prefix="/dashboard", include_in_schema=False)

    @public.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="dashboard/login.html",
            context={"error": None},
        )

    @public.post("/login", response_class=HTMLResponse)
    async def login_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> Any:
        result = await login_handler(request, username=username, password=password)
        if isinstance(result, dict) and "error" in result:
            return templates.TemplateResponse(
                request=request,
                name="dashboard/login.html",
                context={"error": result["error"]},
                status_code=401,
            )
        return result

    @public.post("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/dashboard/login", status_code=303)

    # --- OAuth2 routes (if configured) ---
    if oauth2_config and discovery_client:
        from agent_gateway.dashboard.oauth2 import (
            make_authorize_handler,
            make_callback_handler,
        )

        authorize_handler = make_authorize_handler(oauth2_config, discovery_client)
        callback_handler = make_callback_handler(oauth2_config, discovery_client)

        public.add_api_route(
            "/oauth2/authorize", authorize_handler, methods=["GET"], name="oauth2_authorize"
        )
        public.add_api_route(
            "/oauth2/callback", callback_handler, methods=["GET"], name="oauth2_callback"
        )

    # --- Protected router ---
    protected = APIRouter(
        prefix="/dashboard",
        include_in_schema=False,
        dependencies=[Depends(get_dashboard_user)],
    )

    @protected.get("/", response_class=HTMLResponse)
    @protected.get("/agents", response_class=HTMLResponse)
    async def agents_page(
        request: Request,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        ws = gw.workspace
        agents = list(ws.agents.values()) if ws else []

        # Fetch user configs for personal agent badges
        user_configs_by_agent: dict[str, Any] = {}
        if current_user.username and current_user.username != "anonymous":
            try:
                user_configs = await gw._user_agent_config_repo.list_by_user(current_user.username)
                user_configs_by_agent = {uc.agent_id: uc for uc in user_configs}
            except Exception:
                logger.debug("Failed to fetch user configs for dashboard", exc_info=True)

        # Determine which agents have running executions
        busy_agents: set[str] = set()
        try:
            running_records = await gw._execution_repo.list_all(limit=100, status="running")
            for rec in running_records:
                busy_agents.add(rec.agent_id)
            queued_records = await gw._execution_repo.list_all(limit=100, status="queued")
            for rec in queued_records:
                busy_agents.add(rec.agent_id)
        except Exception:
            logger.debug("Failed to fetch running executions for status badges", exc_info=True)

        cards = []
        for a in agents:
            card = AgentCard.from_definition(a, user_config=user_configs_by_agent.get(a.id))
            if a.scope == "personal" and not card.user_configured:
                card.status = "setup_required"
            elif a.id in busy_agents:
                card.status = "busy"
            else:
                card.status = "online"
            cards.append(card)

        workspace_errors = ws.errors if ws else []

        is_htmx = bool(request.headers.get("HX-Request"))
        template = "dashboard/_agent_cards.html" if is_htmx else "dashboard/agents.html"
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "agents": cards,
                "workspace_errors": workspace_errors,
                "current_user": current_user,
                "active_page": "agents",
            },
        )

    @protected.get("/agents/{agent_id}/setup", response_class=HTMLResponse, response_model=None)
    async def agent_setup_page(
        request: Request,
        agent_id: str,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse | RedirectResponse:
        gw = request.app
        ws = gw.workspace
        agent = ws.agents.get(agent_id) if ws else None
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent.scope != "personal":
            return RedirectResponse(url=f"/dashboard/chat?agent_id={agent_id}", status_code=303)

        agent_name = agent.display_name or agent_id
        setup_schema = agent.setup_schema or {}
        required_fields = set(setup_schema.get("required", []))

        # Load existing config
        existing_config: dict[str, Any] = {}
        existing_secrets: set[str] = set()
        existing_instructions: str | None = None
        has_existing_config = False

        # Fetch existing user schedule for this agent
        user_schedule = None
        if current_user.username and current_user.username != "anonymous":
            config = await gw._user_agent_config_repo.get(current_user.username, agent_id)
            if config is not None:
                has_existing_config = True
                existing_config = dict(config.config_values)
                existing_secrets = set(config.encrypted_secrets.keys())
                existing_instructions = config.instructions

            # Find user's schedule for this agent
            try:
                all_user_schedules = await gw._user_schedule_repo.list_by_user(
                    current_user.username
                )
                for sched in all_user_schedules:
                    if sched.agent_id == agent_id:
                        user_schedule = sched
                        break
            except Exception:
                logger.debug("Failed to fetch user schedule for setup page", exc_info=True)

        return templates.TemplateResponse(
            request=request,
            name="dashboard/agent_setup.html",
            context={
                "agent_id": agent_id,
                "agent_name": agent_name,
                "setup_schema": setup_schema,
                "required_fields": required_fields,
                "existing_config": existing_config,
                "existing_secrets": existing_secrets,
                "existing_instructions": existing_instructions,
                "has_existing_config": has_existing_config,
                "user_schedule": user_schedule,
                "error": None,
                "success": None,
                "current_user": current_user,
                "active_page": "agents",
            },
        )

    @protected.post("/agents/{agent_id}/setup", response_class=HTMLResponse)
    async def agent_setup_save(
        request: Request,
        agent_id: str,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> Any:
        from datetime import UTC, datetime

        from agent_gateway.persistence.domain import UserAgentConfig
        from agent_gateway.secrets import encrypt_value, get_sensitive_fields

        gw = request.app
        ws = gw.workspace
        agent = ws.agents.get(agent_id) if ws else None
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        user_id = current_user.username
        if not user_id or user_id == "anonymous":
            raise HTTPException(status_code=401, detail="Authentication required")

        form_data = await request.form()
        setup_schema = agent.setup_schema or {}
        properties = setup_schema.get("properties", {})
        sensitive_fields = get_sensitive_fields(setup_schema) if setup_schema else set()
        required = set(setup_schema.get("required", []))

        # Load existing config to preserve secrets not re-entered
        existing = await gw._user_agent_config_repo.get(user_id, agent_id)
        existing_encrypted = dict(existing.encrypted_secrets) if existing else {}

        raw_instructions = form_data.get("instructions")
        instructions = str(raw_instructions).strip() if raw_instructions else None
        config_values: dict[str, Any] = {}
        encrypted_secrets: dict[str, Any] = {}

        for prop_name, prop in properties.items():
            raw = form_data.get(prop_name, "")
            raw_str = str(raw).strip() if raw else ""
            prop_type = prop.get("type", "string")

            if prop_name in sensitive_fields:
                if raw_str:
                    encrypted_secrets[prop_name] = encrypt_value(raw_str)
                elif prop_name in existing_encrypted:
                    encrypted_secrets[prop_name] = existing_encrypted[prop_name]
            elif prop_type == "boolean":
                config_values[prop_name] = raw_str == "true"
            elif prop_type in ("integer", "number"):
                if raw_str:
                    try:
                        config_values[prop_name] = (
                            int(raw_str) if prop_type == "integer" else float(raw_str)
                        )
                    except ValueError:
                        config_values[prop_name] = raw_str
                elif prop_name not in required:
                    pass  # skip optional empty numeric
            elif prop_type == "array":
                if raw_str:
                    config_values[prop_name] = [v.strip() for v in raw_str.split(",") if v.strip()]
                else:
                    config_values[prop_name] = []
            else:
                if raw_str:
                    config_values[prop_name] = raw_str

        # Determine if setup is complete
        provided = set(config_values.keys()) | set(encrypted_secrets.keys())
        setup_completed = required.issubset(provided)

        now = datetime.now(UTC)
        config = UserAgentConfig(
            user_id=user_id,
            agent_id=agent_id,
            instructions=instructions,
            config_values=config_values,
            encrypted_secrets=encrypted_secrets,
            setup_completed=setup_completed,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        await gw._user_agent_config_repo.upsert(config)

        # Handle schedule settings from the setup form
        schedule_enabled = form_data.get("schedule_enabled") == "true"
        schedule_cron = str(form_data.get("schedule_cron", "")).strip()
        schedule_label = str(form_data.get("schedule_label", "")).strip()
        schedule_message_val = str(form_data.get("schedule_message", "")).strip()

        # Find existing user schedule for this agent
        existing_schedule = None
        try:
            all_user_schedules = await gw._user_schedule_repo.list_by_user(user_id)
            for sched in all_user_schedules:
                if sched.agent_id == agent_id:
                    existing_schedule = sched
                    break
        except Exception:
            logger.debug("Failed to fetch user schedules during setup save", exc_info=True)

        if schedule_enabled and schedule_cron:
            from apscheduler.triggers.cron import CronTrigger

            try:
                CronTrigger.from_crontab(schedule_cron)
            except (ValueError, KeyError):
                pass  # Skip invalid cron — don't block the config save
            else:
                import uuid

                from agent_gateway.persistence.domain import UserScheduleRecord

                if existing_schedule is not None:
                    # Update existing schedule
                    await gw._user_schedule_repo.update_enabled(existing_schedule.id, True)
                    # For cron/label changes, delete and recreate
                    if (
                        existing_schedule.cron_expr != schedule_cron
                        or existing_schedule.name != schedule_label
                    ):
                        await gw._user_schedule_repo.delete(existing_schedule.id)
                        if gw._scheduler is not None:
                            await gw._scheduler.remove_user_schedule(existing_schedule.id)
                        existing_schedule = None  # force create below

                if existing_schedule is None:
                    sched_id = f"user:{user_id}:{agent_id}:{str(uuid.uuid4())[:8]}"
                    new_sched = UserScheduleRecord(
                        id=sched_id,
                        user_id=user_id,
                        agent_id=agent_id,
                        name=schedule_label or f"{agent_id} schedule",
                        cron_expr=schedule_cron,
                        message=schedule_message_val or "Scheduled run",
                        enabled=True,
                        timezone="UTC",
                        created_at=now,
                    )
                    await gw._user_schedule_repo.create(new_sched)
                    if gw._scheduler is not None:
                        await gw._scheduler.register_user_schedule(
                            schedule_id=sched_id,
                            agent_id=agent_id,
                            cron_expr=schedule_cron,
                            message=schedule_message_val or "Scheduled run",
                            timezone="UTC",
                        )
        elif not schedule_enabled and existing_schedule is not None:
            # Disable existing schedule
            await gw._user_schedule_repo.update_enabled(existing_schedule.id, False)
            if gw._scheduler is not None:
                await gw._scheduler.pause(existing_schedule.id)

        if setup_completed:
            return RedirectResponse(url=f"/dashboard/chat?agent_id={agent_id}", status_code=303)

        # If not complete, show the form again with a message
        return templates.TemplateResponse(
            request=request,
            name="dashboard/agent_setup.html",
            context={
                "agent_id": agent_id,
                "agent_name": agent.display_name or agent_id,
                "setup_schema": setup_schema,
                "required_fields": required,
                "existing_config": config_values,
                "existing_secrets": set(encrypted_secrets.keys()),
                "existing_instructions": instructions,
                "has_existing_config": True,
                "error": "Some required fields are missing. Please complete all required fields.",
                "success": None,
                "current_user": current_user,
                "active_page": "agents",
            },
        )

    @protected.post("/agents/{agent_id}/setup/delete")
    async def agent_setup_delete(
        request: Request,
        agent_id: str,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> RedirectResponse:
        gw = request.app
        user_id = current_user.username
        if user_id and user_id != "anonymous":
            await gw._user_agent_config_repo.delete(user_id, agent_id)
        return RedirectResponse(url="/dashboard/agents", status_code=303)

    @protected.get("/executions", response_class=HTMLResponse)
    async def executions_page(
        request: Request,
        agent_id: str | None = None,
        status: str | None = None,
        session_id: str | None = None,
        page: int = 1,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        repo = gw._execution_repo
        offset = (page - 1) * _PAGE_SIZE

        search: str | None = request.query_params.get("search") or None

        records = await repo.list_all(
            limit=_PAGE_SIZE,
            offset=offset,
            agent_id=agent_id or None,
            status=status or None,
            session_id=session_id or None,
            search=search,
        )
        total = await repo.count_all(
            agent_id=agent_id or None,
            status=status or None,
            session_id=session_id or None,
            search=search,
        )
        rows = [ExecutionRow.from_record(r) for r in records]

        # Summary stats for the stats bar
        exec_stats = await repo.get_summary_stats(days=30)

        ws = gw.workspace
        agent_names = {aid: (a.display_name or aid) for aid, a in ws.agents.items()} if ws else {}

        has_running = any(r.is_running for r in rows)
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

        is_htmx = bool(request.headers.get("HX-Request"))
        template = "dashboard/_exec_rows.html" if is_htmx else "dashboard/executions.html"
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "rows": rows,
                "agent_names": agent_names,
                "agent_id_filter": agent_id or "",
                "status_filter": status or "",
                "search": search or "",
                "page": page,
                "total_pages": total_pages,
                "total": total,
                "exec_stats": exec_stats,
                "has_running": has_running,
                "current_user": current_user,
                "active_page": "executions",
            },
        )

    @protected.get("/executions/{execution_id}", response_class=HTMLResponse)
    async def execution_detail(
        request: Request,
        execution_id: str,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        repo = gw._execution_repo
        record = await repo.get_with_steps(execution_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Execution not found")

        ws = gw.workspace
        agent = ws.agents.get(record.agent_id) if ws else None
        agent_name = (agent.display_name or record.agent_id) if agent else record.agent_id

        detail = ExecutionDetail.from_record(record, agent_name)

        # Build conversation context if this execution is part of a session
        conversation: ConversationDetail | None = None
        record_session_id = record.session_id
        if record_session_id:
            session_records = await repo.list_by_session(record_session_id)
            total_cost = 0.0
            total_in = 0
            total_out = 0
            for r in session_records:
                if r.usage:
                    total_cost += float(r.usage.get("cost_usd", 0) or 0)
                    total_in += int(r.usage.get("input_tokens", 0) or 0)
                    total_out += int(r.usage.get("output_tokens", 0) or 0)
            conversation = ConversationDetail(
                session_id=record_session_id,
                execution_count=len(session_records),
                total_cost_usd=total_cost,
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                executions=[ExecutionRow.from_record(r) for r in session_records],
            )

        # Build delegation context
        parent_execution: ExecutionRow | None = None
        child_executions: list[ExecutionRow] = []
        workflow_cost: float | None = None

        if record.parent_execution_id:
            parent_record = await repo.get(record.parent_execution_id)
            if parent_record:
                parent_execution = ExecutionRow.from_record(parent_record)

        children = await repo.list_children(execution_id)
        if children:
            child_executions = [ExecutionRow.from_record(c) for c in children]

        # Show workflow cost rollup for root executions with children
        if not record.parent_execution_id and child_executions:
            workflow_cost = await repo.cost_by_root_execution(
                record.root_execution_id or execution_id
            )

        is_htmx = bool(request.headers.get("HX-Request"))
        is_running = record.status in ("queued", "running")
        template = (
            "dashboard/_trace_steps.html"
            if (is_htmx and is_running)
            else "dashboard/execution_detail.html"
        )
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "detail": detail,
                "conversation": conversation,
                "parent_execution": parent_execution,
                "child_executions": child_executions,
                "workflow_cost": workflow_cost,
                "is_running": is_running,
                "current_user": current_user,
                "active_page": "executions",
            },
        )

    @protected.post("/executions/{execution_id}/retry")
    async def execution_retry(
        request: Request,
        execution_id: str,
        current_user: DashboardUser = Depends(require_admin),
    ) -> RedirectResponse:
        import uuid

        from agent_gateway.engine.models import ExecutionOptions

        gw = request.app
        repo = gw._execution_repo

        # 1. Fetch original execution
        orig_record = await repo.get(execution_id)
        if orig_record is None:
            raise HTTPException(status_code=404, detail="Execution not found")

        agent_id = orig_record.agent_id
        message = orig_record.message
        session_id = orig_record.session_id

        # 2. Get agent
        ws = gw.workspace
        agent = ws.agents.get(agent_id) if ws else None
        if agent is None:
            raise HTTPException(
                status_code=400, detail=f"Agent '{agent_id}' no longer available in workspace."
            )

        # 3. Create context + session
        user_id = (
            current_user.username
            if current_user.username and current_user.username != "anonymous"
            else None
        )

        # 4. Trigger new execution async
        exec_options = ExecutionOptions()
        new_exec_id = str(uuid.uuid4())

        # We fire and forget this task
        import asyncio

        asyncio.create_task(
            gw.invoke_agent(
                agent_id=agent_id,
                message=message,
                session_id=session_id,
                user_id=user_id,
                options=exec_options,
                execution_id=new_exec_id,
            )
        )

        return RedirectResponse(url=f"/dashboard/executions/{new_exec_id}", status_code=303)

    @protected.get("/conversations", response_class=HTMLResponse)
    async def conversations_page(
        request: Request,
        page: int = 1,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        repo = gw._execution_repo
        offset = (page - 1) * _PAGE_SIZE

        rows_raw = await repo.list_conversations_summary(limit=_PAGE_SIZE, offset=offset)
        total = await repo.count_conversations()
        rows = [ConversationSummaryRow.from_row(r) for r in rows_raw]

        ws = gw.workspace
        agent_names = {aid: (a.display_name or aid) for aid, a in ws.agents.items()} if ws else {}

        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

        return templates.TemplateResponse(
            request=request,
            name="dashboard/conversations.html",
            context={
                "rows": rows,
                "agent_names": agent_names,
                "page": page,
                "total_pages": total_pages,
                "total": total,
                "current_user": current_user,
                "active_page": "conversations",
            },
        )

    @protected.get("/conversations/{session_id}", response_class=HTMLResponse)
    async def conversation_detail_page(
        request: Request,
        session_id: str,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        repo = gw._execution_repo

        records = await repo.list_by_session(session_id, limit=200)
        if not records:
            raise HTTPException(status_code=404, detail="Conversation not found")

        exec_rows = [ExecutionRow.from_record(r) for r in reversed(records)]  # oldest first

        total_cost = 0.0
        total_in = 0
        total_out = 0
        for r in records:
            if r.usage:
                total_cost += float(r.usage.get("cost_usd", 0) or 0)
                total_in += int(r.usage.get("input_tokens", 0) or 0)
                total_out += int(r.usage.get("output_tokens", 0) or 0)

        ws = gw.workspace
        agent_id = records[0].agent_id
        agent = ws.agents.get(agent_id) if ws else None
        agent_name = (agent.display_name or agent_id) if agent else agent_id

        conversation = ConversationDetail(
            session_id=session_id,
            execution_count=len(records),
            total_cost_usd=total_cost,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            executions=exec_rows,
        )

        return templates.TemplateResponse(
            request=request,
            name="dashboard/conversation_detail.html",
            context={
                "conversation": conversation,
                "agent_name": agent_name,
                "agent_id": agent_id,
                "current_user": current_user,
                "active_page": "conversations",
            },
        )

    @protected.get("/chat", response_class=HTMLResponse)
    async def chat_page(
        request: Request,
        agent_id: str | None = None,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        ws = gw.workspace
        agents = list(ws.agents.values()) if ws else []

        # Fetch user configs for personal agent status
        user_configs_by_agent: dict[str, Any] = {}
        if current_user.username and current_user.username != "anonymous":
            try:
                user_configs = await gw._user_agent_config_repo.list_by_user(current_user.username)
                user_configs_by_agent = {uc.agent_id: uc for uc in user_configs}
            except Exception:
                logger.debug("Failed to fetch user configs for chat", exc_info=True)

        agent_cards = [
            AgentCard.from_definition(a, user_config=user_configs_by_agent.get(a.id))
            for a in agents
        ]
        selected_agent_id = agent_id or (agents[0].id if agents else None)
        return templates.TemplateResponse(
            request=request,
            name="dashboard/chat.html",
            context={
                "agents": agent_cards,
                "selected_agent_id": selected_agent_id,
                "session_id": None,
                "messages": [],
                "current_user": current_user,
                "active_page": "chat",
            },
        )

    @protected.post("/chat/stream")
    async def chat_stream(
        request: Request,
        agent_id: str = Form(...),
        message: str = Form(...),
        session_id: str = Form(""),
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> StreamingResponse:
        from agent_gateway.engine.models import ExecutionHandle, ExecutionOptions
        from agent_gateway.engine.streaming import stream_chat_execution
        from agent_gateway.workspace.prompt import assemble_system_prompt

        gw = request.app

        # Derive user_id from dashboard user (OAuth2 subject or username)
        user_id: str | None = None
        if current_user.username and current_user.username != "anonymous":
            user_id = current_user.username
            # Ensure user profile exists so memory block can reference name
            await gw._ensure_dashboard_user_profile(current_user)

        async def event_generator() -> Any:
            try:
                snapshot = gw._snapshot
                if snapshot is None or snapshot.workspace is None:
                    msg = json.dumps({"message": "Workspace not loaded"})
                    yield f"event: error\ndata: {msg}\n\n"
                    return

                agent = snapshot.workspace.agents.get(agent_id)
                if agent is None:
                    yield (
                        f"event: error\ndata: "
                        f"{json.dumps({'message': f'Agent {agent_id!r} not found'})}\n\n"
                    )
                    return

                # Personal agent guard: check setup before streaming
                user_instructions: str | None = None
                if agent.scope == "personal":
                    if not user_id:
                        err = {"message": "Auth required for personal agents"}
                        yield f"event: error\ndata: {json.dumps(err)}\n\n"
                        return
                    user_agent_config = await gw._user_agent_config_repo.get(user_id, agent_id)
                    if user_agent_config is None or not user_agent_config.setup_completed:
                        setup_url = f"/dashboard/agents/{agent_id}/setup"
                        err = {
                            "message": "Setup required before chatting.",
                            "setup_url": setup_url,
                        }
                        yield f"event: error\ndata: {json.dumps(err)}\n\n"
                        return
                    user_instructions = user_agent_config.instructions

                session_store = gw._session_store
                if session_store is None:
                    yield (
                        f"event: error\ndata: "
                        f"{json.dumps({'message': 'Session store not available'})}\n\n"
                    )
                    return

                if session_id:
                    session = session_store.get_session(session_id)
                    if session is None or session.agent_id != agent_id:
                        session = session_store.create_session(agent_id, user_id=user_id)
                else:
                    session = session_store.create_session(agent_id, user_id=user_id)

                session.append_user_message(message)
                session.truncate_history(session_store._max_history)

                retriever_reg = snapshot.retriever_registry
                system_prompt = await assemble_system_prompt(
                    agent,
                    snapshot.workspace,
                    query=message,
                    retriever_registry=retriever_reg,
                    context_retrieval_config=snapshot.context_retrieval_config,
                    chat_mode=True,
                )

                # Inject user instructions for personal agents
                if user_instructions:
                    system_prompt = f"{system_prompt}\n\n## User Instructions\n{user_instructions}"

                # Inject memory context (user name + memories) into system prompt
                memory_block = await gw._get_memory_block(
                    agent_id, message, agent.memory_config, user_id=user_id
                )
                if memory_block:
                    system_prompt = f"{system_prompt}\n\n{memory_block}"

                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": system_prompt},
                    *session.messages,
                ]

                exec_options = ExecutionOptions()
                import uuid

                execution_id = str(uuid.uuid4())
                handle = ExecutionHandle(execution_id)
                gw._execution_handles[execution_id] = handle

                try:
                    collected_text: list[str] = []
                    async for event in stream_chat_execution(
                        gw=gw,
                        agent=agent,
                        session=session,
                        messages=messages,
                        exec_options=exec_options,
                        execution_id=execution_id,
                        handle=handle,
                    ):
                        # Collect assistant text for persistence + memory extraction
                        if isinstance(event, str) and "event: token\n" in event:
                            for line in event.split("\n"):
                                if line.startswith("data: "):
                                    try:
                                        payload = json.loads(line[6:])
                                        collected_text.append(payload.get("content", ""))
                                    except (json.JSONDecodeError, KeyError):
                                        pass
                        yield event
                finally:
                    gw._execution_handles.pop(execution_id, None)

                    # Persist conversation and trigger memory extraction
                    assistant_text = "".join(collected_text) if collected_text else None
                    if assistant_text:
                        gw._persist_conversation_messages(session, message, assistant_text)
                        gw._trigger_memory_extraction(
                            agent_id, message, assistant_text, user_id=user_id
                        )
            except Exception as e:
                logger.exception("Unexpected error in chat stream generator")
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @protected.get("/schedules", response_class=HTMLResponse)
    async def schedules_page(
        request: Request,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        schedule_repo = gw._schedule_repo
        exec_repo = gw._execution_repo
        records = await schedule_repo.list_all()

        # Fetch user's personal schedules
        user_schedules: list[Any] = []
        if current_user.username and current_user.username != "anonymous":
            try:
                user_schedules = await gw._user_schedule_repo.list_by_user(current_user.username)
            except Exception:
                logger.debug("Failed to fetch user schedules", exc_info=True)

        # Schedule execution stats for the stats bar
        schedule_stats = await exec_repo.get_schedule_stats(hours=24)

        ws = gw.workspace
        agent_names = {aid: (a.display_name or aid) for aid, a in ws.agents.items()} if ws else {}

        return templates.TemplateResponse(
            request=request,
            name="dashboard/schedules.html",
            context={
                "schedules": records,
                "user_schedules": user_schedules,
                "schedule_stats": schedule_stats,
                "agent_names": agent_names,
                "current_user": current_user,
                "active_page": "schedules",
            },
        )

    @protected.post("/schedules/{schedule_id}/toggle")
    async def toggle_schedule(
        request: Request,
        schedule_id: str,
        current_user: DashboardUser = Depends(require_admin),
    ) -> RedirectResponse:
        gw = request.app
        schedule_repo = gw._schedule_repo
        record = await schedule_repo.get(schedule_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Schedule not found")

        new_enabled = not record.enabled
        await schedule_repo.update_enabled(schedule_id, new_enabled)
        if gw._scheduler is not None:
            if new_enabled:
                await gw._scheduler.resume(schedule_id)
            else:
                await gw._scheduler.pause(schedule_id)

        return RedirectResponse(url="/dashboard/schedules", status_code=303)

    @protected.get("/my-schedules", response_class=HTMLResponse)
    async def my_schedules_page(
        request: Request,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        user_id = current_user.username
        if not user_id or user_id == "anonymous":
            raise HTTPException(status_code=401, detail="Authentication required")

        user_schedules = await gw._user_schedule_repo.list_by_user(user_id)

        ws = gw.workspace
        agents = list(ws.agents.values()) if ws else []
        agent_names = {a.id: (a.display_name or a.id) for a in agents}

        # Only show configured personal agents for the add form
        user_configs_by_agent: dict[str, Any] = {}
        try:
            user_configs = await gw._user_agent_config_repo.list_by_user(user_id)
            user_configs_by_agent = {uc.agent_id: uc for uc in user_configs}
        except Exception:
            pass

        available_agents = [
            AgentCard.from_definition(a, user_config=user_configs_by_agent.get(a.id))
            for a in agents
            if a.scope != "personal"
            or (
                user_configs_by_agent.get(a.id) is not None
                and getattr(user_configs_by_agent.get(a.id), "setup_completed", False)
            )
        ]

        # Expose available notification backends for the form
        import contextlib

        notification_channels: list[str] = []
        with contextlib.suppress(Exception):
            notification_channels = list(gw._notification_engine._backends.keys())

        return templates.TemplateResponse(
            request=request,
            name="dashboard/user_schedules.html",
            context={
                "user_schedules": user_schedules,
                "agent_names": agent_names,
                "available_agents": available_agents,
                "notification_channels": notification_channels,
                "current_user": current_user,
                "active_page": "my-schedules",
            },
        )

    @protected.post("/my-schedules")
    async def create_user_schedule(
        request: Request,
        agent_id: str = Form(...),
        name: str = Form(...),
        cron_expr: str = Form(...),
        schedule_message: str = Form(...),
        timezone: str = Form("UTC"),
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> RedirectResponse:
        import uuid

        from agent_gateway.persistence.domain import UserScheduleRecord

        gw = request.app
        user_id = current_user.username
        if not user_id or user_id == "anonymous":
            raise HTTPException(status_code=401, detail="Authentication required")

        # Validate cron expression
        from apscheduler.triggers.cron import CronTrigger

        try:
            CronTrigger.from_crontab(cron_expr, timezone=timezone)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail="Invalid cron expression") from exc

        from datetime import UTC, datetime

        # Build notify config from form data
        form_data = await request.form()
        notify: dict[str, Any] | None = None
        if form_data.get("notify_enabled") == "on":
            targets: list[dict[str, Any]] = []
            notify_channel = str(form_data.get("notify_channel", "slack"))
            notify_target = str(form_data.get("notify_target", "")).strip()
            if notify_channel and notify_target:
                targets.append({"channel": notify_channel, "target": notify_target})
            if targets:
                on_complete = targets if form_data.get("notify_on_complete") == "on" else []
                on_error = targets if form_data.get("notify_on_error") == "on" else []
                notify = {
                    "on_complete": [t for t in on_complete],
                    "on_error": [t for t in on_error],
                    "on_timeout": [],
                }

        schedule_id = f"user:{user_id}:{agent_id}:{str(uuid.uuid4())[:8]}"
        record = UserScheduleRecord(
            id=schedule_id,
            user_id=user_id,
            agent_id=agent_id,
            name=name,
            cron_expr=cron_expr,
            message=schedule_message,
            enabled=True,
            timezone=timezone,
            notify=notify,
            created_at=datetime.now(UTC),
        )
        await gw._user_schedule_repo.create(record)

        # Register with scheduler if available
        if gw._scheduler is not None:
            await gw._scheduler.register_user_schedule(
                schedule_id=schedule_id,
                agent_id=agent_id,
                cron_expr=cron_expr,
                message=schedule_message,
                timezone=timezone,
                notify=notify,
            )

        return RedirectResponse(url="/dashboard/my-schedules", status_code=303)

    @protected.post("/my-schedules/{schedule_id}/toggle")
    async def toggle_user_schedule(
        request: Request,
        schedule_id: str,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> RedirectResponse:
        gw = request.app
        user_id = current_user.username
        record = await gw._user_schedule_repo.get(schedule_id)
        if record is None or record.user_id != user_id:
            raise HTTPException(status_code=404, detail="Schedule not found")

        new_enabled = not record.enabled
        await gw._user_schedule_repo.update_enabled(schedule_id, new_enabled)
        if gw._scheduler is not None:
            if new_enabled:
                await gw._scheduler.resume(schedule_id)
            else:
                await gw._scheduler.pause(schedule_id)

        return RedirectResponse(url="/dashboard/my-schedules", status_code=303)

    @protected.post("/my-schedules/{schedule_id}/delete")
    async def delete_user_schedule(
        request: Request,
        schedule_id: str,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> RedirectResponse:
        gw = request.app
        user_id = current_user.username
        record = await gw._user_schedule_repo.get(schedule_id)
        if record is None or record.user_id != user_id:
            raise HTTPException(status_code=404, detail="Schedule not found")

        await gw._user_schedule_repo.delete(schedule_id)
        if gw._scheduler is not None:
            await gw._scheduler.remove_user_schedule(schedule_id)

        return RedirectResponse(url="/dashboard/my-schedules", status_code=303)

    @protected.get("/analytics", response_class=HTMLResponse)
    async def analytics_page(
        request: Request,
        days: int = 30,
        current_user: DashboardUser = Depends(get_dashboard_user),
    ) -> HTMLResponse:
        gw = request.app
        repo = gw._execution_repo
        persistence_enabled = gw._config.persistence.enabled if gw._config else True

        cost_by_day_data: list[dict[str, Any]] = []
        exec_by_day_data: list[dict[str, Any]] = []
        cost_by_agent_data: list[dict[str, Any]] = []
        total_cost = 0.0
        total_execs = 0
        success_count = 0

        stats = {
            "total_executions": 0,
            "success_count": 0,
            "total_cost_usd": 0.0,
            "avg_duration_ms": 0.0,
        }
        if persistence_enabled:
            try:
                stats = await repo.get_summary_stats(days=days)
            except Exception:
                logger.debug("Failed to fetch summary stats", exc_info=True)

            cost_by_day_data = await repo.cost_by_day(days=days)
            exec_by_day_data = await repo.executions_by_day(days=days)
            cost_by_agent_data = await repo.cost_by_agent(days=days)

        total_execs = int(stats["total_executions"])
        total_cost = float(stats["total_cost_usd"])
        success_count = int(stats["success_count"])
        avg_duration_ms = stats["avg_duration_ms"]
        success_rate = (success_count / total_execs * 100) if total_execs > 0 else 0.0

        ws = gw.workspace
        agent_names = {aid: (a.display_name or aid) for aid, a in ws.agents.items()} if ws else {}

        summary = AnalyticsSummary(
            total_cost_usd=total_cost,
            total_executions=total_execs,
            success_rate=success_rate,
            avg_duration_ms=avg_duration_ms,
            cost_by_day=cost_by_day_data,
            executions_by_day=exec_by_day_data,
            cost_by_agent=cost_by_agent_data,
            days=days,
        )

        # Build Agent Cards for the grid
        agents = list(ws.agents.values()) if ws else []
        # Fetch user configs for personal agent badges
        user_configs_by_agent: dict[str, Any] = {}
        if current_user.username and current_user.username != "anonymous":
            try:
                user_configs = await gw._user_agent_config_repo.list_by_user(current_user.username)
                user_configs_by_agent = {uc.agent_id: uc for uc in user_configs}
            except Exception:
                pass

        agent_cards = [
            AgentCard.from_definition(a, user_config=user_configs_by_agent.get(a.id))
            for a in agents[:3]  # Show top 3 in the grid
        ]

        is_htmx = bool(request.headers.get("HX-Request"))
        template = "dashboard/_analytics_charts.html" if is_htmx else "dashboard/analytics.html"
        return templates.TemplateResponse(
            request=request,
            name=template,
            context={
                "summary": summary,
                "days": days,
                "persistence_enabled": persistence_enabled,
                "agent_names": agent_names,
                "agents": agent_cards,
                "cost_by_agent": cost_by_agent_data,
                "current_user": current_user,
                "active_page": "analytics",
            },
        )

    app.include_router(public)
    app.include_router(protected)
