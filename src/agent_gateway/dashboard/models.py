"""View models for the dashboard — plain dataclasses derived from domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent_gateway.persistence.domain import ExecutionRecord, ExecutionStep, UserAgentConfig
from agent_gateway.workspace.agent import AgentDefinition


@dataclass
class AgentCard:
    id: str
    display_name: str
    description: str
    tags: list[str]
    model: str
    execution_mode: str
    skills_count: int
    has_memory: bool
    has_schedules: bool
    initials: str  # 2-char avatar initials
    scope: str = "global"
    is_personal: bool = False
    user_configured: bool = False
    status: str = "online"  # "online" | "busy" | "setup_required"

    @classmethod
    def from_definition(
        cls,
        agent: AgentDefinition,
        user_config: UserAgentConfig | None = None,
    ) -> AgentCard:
        name = agent.display_name or agent.id
        words = name.replace("-", " ").replace("_", " ").split()
        initials = (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1])).upper()
        is_personal = agent.scope == "personal"
        return cls(
            id=agent.id,
            display_name=name,
            description=agent.description or "",
            tags=agent.tags or [],
            model=agent.model.name or "default",
            execution_mode=agent.execution_mode,
            skills_count=len(agent.skills),
            has_memory=agent.memory_config.enabled if agent.memory_config else False,
            has_schedules=len(agent.schedules) > 0,
            initials=initials[:2] if len(initials) >= 2 else initials.ljust(2, "?"),
            scope=agent.scope,
            is_personal=is_personal,
            user_configured=user_config.setup_completed if user_config else False,
        )


@dataclass
class ExecutionRow:
    id: str
    id_short: str
    agent_id: str
    status: str
    message_preview: str
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    created_at: datetime | None
    is_running: bool
    session_id: str | None

    @classmethod
    def from_record(cls, record: ExecutionRecord) -> ExecutionRow:
        usage = record.usage or {}
        duration: int | None = None
        if record.started_at and record.completed_at:
            duration = int((record.completed_at - record.started_at).total_seconds() * 1000)
        # Prefer direct session_id field, fall back to options for legacy data.
        # TODO: remove options fallback once all deployments have migrated.
        sid = record.session_id
        if sid is None:
            options = record.options or {}
            sid = options.get("session_id")
        return cls(
            id=record.id,
            id_short=record.id[:8],
            agent_id=record.agent_id,
            status=record.status,
            message_preview=(record.message or "")[:80],
            cost_usd=usage.get("cost_usd"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            duration_ms=duration,
            created_at=record.created_at,
            is_running=record.status in ("queued", "running"),
            session_id=sid,
        )


@dataclass
class TraceStepView:
    id: int | None
    step_type: str  # llm_call | tool_call | tool_result
    sequence: int
    duration_ms: int
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def is_llm_call(self) -> bool:
        return self.step_type == "llm_call"

    @property
    def is_tool_call(self) -> bool:
        return self.step_type == "tool_call"

    @property
    def is_tool_result(self) -> bool:
        return self.step_type == "tool_result"

    @classmethod
    def from_step(cls, step: ExecutionStep) -> TraceStepView:
        return cls(
            id=step.id,
            step_type=step.step_type,
            sequence=step.sequence,
            duration_ms=step.duration_ms,
            data=step.data or {},
        )


@dataclass
class ExecutionDetail:
    record: ExecutionRecord
    steps: list[TraceStepView]
    agent_display_name: str
    total_cost_usd: float | None
    total_input_tokens: int | None
    total_output_tokens: int | None
    duration_ms: int | None
    models_used: list[str]

    @classmethod
    def from_record(cls, record: ExecutionRecord, agent_name: str) -> ExecutionDetail:
        usage = record.usage or {}
        duration: int | None = None
        if record.started_at and record.completed_at:
            duration = int((record.completed_at - record.started_at).total_seconds() * 1000)
        steps = [TraceStepView.from_step(s) for s in (record.steps or [])]
        return cls(
            record=record,
            steps=steps,
            agent_display_name=agent_name,
            total_cost_usd=usage.get("cost_usd"),
            total_input_tokens=usage.get("input_tokens"),
            total_output_tokens=usage.get("output_tokens"),
            duration_ms=duration,
            models_used=usage.get("models_used") or [],
        )


@dataclass
class ConversationSummaryRow:
    """Summary of a conversation for the conversations list page."""

    session_id: str
    session_id_short: str
    agent_id: str
    execution_count: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    first_activity: datetime | None
    last_activity: datetime | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ConversationSummaryRow:
        return cls(
            session_id=row["session_id"],
            session_id_short=row["session_id"][:8],
            agent_id=row["agent_id"],
            execution_count=int(row.get("execution_count", 0)),
            total_cost_usd=float(row.get("total_cost_usd", 0)),
            total_input_tokens=int(row.get("total_input_tokens", 0)),
            total_output_tokens=int(row.get("total_output_tokens", 0)),
            first_activity=row.get("first_activity"),
            last_activity=row.get("last_activity"),
        )


@dataclass
class ConversationDetail:
    """Aggregated stats for a conversation's executions."""

    session_id: str
    execution_count: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    executions: list[ExecutionRow]


@dataclass
class AnalyticsSummary:
    total_cost_usd: float
    total_executions: int
    success_rate: float
    avg_duration_ms: float
    cost_by_day: list[dict[str, Any]]
    executions_by_day: list[dict[str, Any]]
    cost_by_agent: list[dict[str, Any]]
    days: int


def format_cost(cost: float | None) -> str:
    if cost is None:
        return "—"
    if cost < 0.001:
        return f"${cost:.6f}"
    return f"${cost:.4f}"


def format_duration(ms: int | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def relative_time(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 0:
        # Future time
        seconds = abs(seconds)
        if seconds < 60:
            return "in <1m"
        if seconds < 3600:
            return f"in {seconds // 60}m"
        if seconds < 86400:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"in {h}h {m}m" if m else f"in {h}h"
        return f"in {seconds // 86400}d"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def format_datetime(dt: datetime | None) -> str:
    """Format a datetime as a readable absolute string, e.g. 'Feb 21, 16:30 UTC'."""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.strftime("%b %d, %H:%M %Z")
