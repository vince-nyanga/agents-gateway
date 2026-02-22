"""Tests for dashboard view models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_gateway.dashboard.models import (
    AgentCard,
    ConversationSummaryRow,
    ExecutionDetail,
    TraceStepView,
    format_cost,
    format_datetime,
    format_duration,
    relative_time,
)
from agent_gateway.persistence.domain import (
    ExecutionRecord,
    ExecutionStep,
    UserAgentConfig,
)
from agent_gateway.workspace.agent import AgentDefinition


def _make_agent(agent_id: str = "test-agent", scope: str = "global") -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        path=Path("/tmp/agents") / agent_id,
        agent_prompt="You are a test agent.",
        display_name="Test Agent",
        scope=scope,
    )


def test_agent_card_global_agent():
    agent = _make_agent()
    card = AgentCard.from_definition(agent)
    assert card.scope == "global"
    assert card.is_personal is False
    assert card.user_configured is False


def test_agent_card_personal_unconfigured():
    agent = _make_agent(scope="personal")
    card = AgentCard.from_definition(agent)
    assert card.scope == "personal"
    assert card.is_personal is True
    assert card.user_configured is False


def test_agent_card_personal_configured():
    agent = _make_agent(scope="personal")
    config = UserAgentConfig(
        user_id="user-1",
        agent_id="test-agent",
        setup_completed=True,
    )
    card = AgentCard.from_definition(agent, user_config=config)
    assert card.is_personal is True
    assert card.user_configured is True


def test_agent_card_personal_incomplete_config():
    agent = _make_agent(scope="personal")
    config = UserAgentConfig(
        user_id="user-1",
        agent_id="test-agent",
        setup_completed=False,
    )
    card = AgentCard.from_definition(agent, user_config=config)
    assert card.is_personal is True
    assert card.user_configured is False


# --- Formatting helper tests ---


class TestFormatCost:
    def test_none(self) -> None:
        assert format_cost(None) == "—"

    def test_tiny_cost(self) -> None:
        assert format_cost(0.0001) == "$0.000100"

    def test_normal_cost(self) -> None:
        result = format_cost(1.2345)
        assert result == "$1.2345"

    def test_zero(self) -> None:
        assert format_cost(0.0) == "$0.000000"


class TestFormatDuration:
    def test_none(self) -> None:
        assert format_duration(None) == "—"

    def test_milliseconds(self) -> None:
        assert format_duration(500) == "500ms"

    def test_seconds(self) -> None:
        assert format_duration(2500) == "2.5s"

    def test_exact_second(self) -> None:
        assert format_duration(1000) == "1.0s"


class TestRelativeTime:
    def test_none(self) -> None:
        assert relative_time(None) == "—"

    def test_just_now(self) -> None:
        now = datetime.now(UTC)
        assert relative_time(now) == "just now"

    def test_minutes_ago(self) -> None:
        past = datetime.now(UTC) - timedelta(minutes=5)
        assert relative_time(past) == "5m ago"

    def test_hours_ago(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=3)
        assert relative_time(past) == "3h ago"

    def test_days_ago(self) -> None:
        past = datetime.now(UTC) - timedelta(days=2)
        assert relative_time(past) == "2d ago"

    def test_future_seconds(self) -> None:
        future = datetime.now(UTC) + timedelta(seconds=30)
        assert relative_time(future) == "in <1m"

    def test_future_minutes(self) -> None:
        future = datetime.now(UTC) + timedelta(minutes=10)
        result = relative_time(future)
        assert result in ("in 9m", "in 10m")

    def test_future_hours(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=2)
        result = relative_time(future)
        assert result.startswith("in 2h") or result.startswith("in 1h")

    def test_future_hours_with_minutes(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=1, minutes=30)
        result = relative_time(future)
        assert result.startswith("in 1h")

    def test_future_days(self) -> None:
        future = datetime.now(UTC) + timedelta(days=5)
        result = relative_time(future)
        assert result in ("in 4d", "in 5d")

    def test_naive_datetime(self) -> None:
        # Naive datetime should be treated as UTC
        past = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=3)
        result = relative_time(past)
        assert "m ago" in result


class TestFormatDatetime:
    def test_none(self) -> None:
        assert format_datetime(None) == "—"

    def test_with_tz(self) -> None:
        dt = datetime(2026, 2, 21, 16, 30, 0, tzinfo=UTC)
        result = format_datetime(dt)
        assert "Feb 21" in result
        assert "16:30" in result

    def test_naive_datetime(self) -> None:
        dt = datetime(2026, 1, 15, 9, 45, 0)
        result = format_datetime(dt)
        assert "Jan 15" in result
        assert "09:45" in result


class TestTraceStepView:
    def test_is_llm_call(self) -> None:
        view = TraceStepView(id=1, step_type="llm_call", sequence=1, duration_ms=100)
        assert view.is_llm_call is True
        assert view.is_tool_call is False
        assert view.is_tool_result is False

    def test_is_tool_call(self) -> None:
        view = TraceStepView(id=2, step_type="tool_call", sequence=2, duration_ms=50)
        assert view.is_tool_call is True
        assert view.is_llm_call is False

    def test_is_tool_result(self) -> None:
        view = TraceStepView(id=3, step_type="tool_result", sequence=3, duration_ms=0)
        assert view.is_tool_result is True

    def test_from_step(self) -> None:
        step = ExecutionStep(
            execution_id="exec-1",
            step_type="llm_call",
            sequence=1,
            id=42,
            data={"model": "gpt-4o"},
            duration_ms=150,
        )
        view = TraceStepView.from_step(step)
        assert view.id == 42
        assert view.step_type == "llm_call"
        assert view.data == {"model": "gpt-4o"}


class TestExecutionDetail:
    def test_from_record_with_duration(self) -> None:
        now = datetime.now(UTC)
        record = ExecutionRecord(
            id="exec-1",
            agent_id="agent-1",
            status="completed",
            started_at=now - timedelta(seconds=2),
            completed_at=now,
            usage={"cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50},
        )
        detail = ExecutionDetail.from_record(record, "My Agent")
        assert detail.agent_display_name == "My Agent"
        assert detail.duration_ms is not None
        assert detail.duration_ms >= 1900
        assert detail.total_cost_usd == 0.01

    def test_from_record_without_timing(self) -> None:
        record = ExecutionRecord(id="exec-2", agent_id="agent-1", status="queued")
        detail = ExecutionDetail.from_record(record, "Agent")
        assert detail.duration_ms is None
        assert detail.total_cost_usd is None


class TestConversationSummaryRow:
    def test_from_row(self) -> None:
        row = {
            "session_id": "abcdef1234567890",
            "agent_id": "assistant",
            "execution_count": 5,
            "total_cost_usd": 0.05,
            "total_input_tokens": 500,
            "total_output_tokens": 250,
            "first_activity": datetime.now(UTC) - timedelta(hours=1),
            "last_activity": datetime.now(UTC),
        }
        summary = ConversationSummaryRow.from_row(row)
        assert summary.session_id_short == "abcdef12"
        assert summary.execution_count == 5
        assert summary.total_cost_usd == 0.05
