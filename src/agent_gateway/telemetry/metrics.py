"""OpenTelemetry metric definitions for Agent Gateway."""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry.metrics import Counter, Histogram, Meter, UpDownCounter, get_meter


@dataclass
class AgentGatewayMetrics:
    """Container for all Agent Gateway metrics instruments."""

    executions_total: Counter
    executions_duration: Histogram
    llm_calls_total: Counter
    llm_duration: Histogram
    llm_tokens_input: Counter
    llm_tokens_output: Counter
    llm_cost_usd: Counter
    tools_calls_total: Counter
    tools_duration: Histogram
    schedules_runs_total: Counter
    schedules_fires_total: Counter
    schedules_active: UpDownCounter

    # Queue metrics
    queue_jobs_enqueued: Counter
    queue_jobs_completed: Counter
    queue_jobs_failed: Counter
    queue_job_duration: Histogram
    queue_depth: UpDownCounter


def create_metrics(meter: Meter | None = None) -> AgentGatewayMetrics:
    """Create all Agent Gateway metric instruments.

    Args:
        meter: OpenTelemetry Meter instance. If None, uses the global meter.
    """
    if meter is None:
        meter = get_meter("agent-gateway")

    return AgentGatewayMetrics(
        executions_total=meter.create_counter(
            "agw.executions.total",
            description="Total number of agent executions",
            unit="1",
        ),
        executions_duration=meter.create_histogram(
            "agw.executions.duration_ms",
            description="Duration of agent executions in milliseconds",
            unit="ms",
        ),
        llm_calls_total=meter.create_counter(
            "agw.llm.calls.total",
            description="Total number of LLM calls",
            unit="1",
        ),
        llm_duration=meter.create_histogram(
            "agw.llm.duration_ms",
            description="Duration of LLM calls in milliseconds",
            unit="ms",
        ),
        llm_tokens_input=meter.create_counter(
            "agw.llm.tokens.input",
            description="Total input tokens consumed",
            unit="1",
        ),
        llm_tokens_output=meter.create_counter(
            "agw.llm.tokens.output",
            description="Total output tokens produced",
            unit="1",
        ),
        llm_cost_usd=meter.create_counter(
            "agw.llm.cost_usd",
            description="Estimated LLM cost in USD",
            unit="USD",
        ),
        tools_calls_total=meter.create_counter(
            "agw.tools.calls.total",
            description="Total number of tool calls",
            unit="1",
        ),
        tools_duration=meter.create_histogram(
            "agw.tools.duration_ms",
            description="Duration of tool executions in milliseconds",
            unit="ms",
        ),
        schedules_runs_total=meter.create_counter(
            "agw.schedules.runs.total",
            description="Total number of scheduled agent runs",
            unit="1",
        ),
        schedules_fires_total=meter.create_counter(
            "agw.schedules.fires.total",
            description="Total number of cron schedule fires (including skipped overlaps)",
            unit="1",
        ),
        schedules_active=meter.create_up_down_counter(
            "agw.schedules.active",
            description="Number of currently enabled schedules",
            unit="1",
        ),
        queue_jobs_enqueued=meter.create_counter(
            "agw.queue.jobs.enqueued",
            description="Total number of jobs enqueued",
            unit="1",
        ),
        queue_jobs_completed=meter.create_counter(
            "agw.queue.jobs.completed",
            description="Total number of jobs completed successfully",
            unit="1",
        ),
        queue_jobs_failed=meter.create_counter(
            "agw.queue.jobs.failed",
            description="Total number of jobs that failed",
            unit="1",
        ),
        queue_job_duration=meter.create_histogram(
            "agw.queue.job.duration_ms",
            description="Duration of queue job processing in milliseconds",
            unit="ms",
        ),
        queue_depth=meter.create_up_down_counter(
            "agw.queue.depth",
            description="Approximate queue depth (incremented on enqueue, decremented on ack)",
            unit="1",
        ),
    )
