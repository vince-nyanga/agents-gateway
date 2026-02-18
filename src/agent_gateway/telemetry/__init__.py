"""OpenTelemetry bootstrap for Agent Gateway.

Telemetry setup never crashes the server — all failures are logged as warnings.
"""

from __future__ import annotations

import logging
import os

from agent_gateway.config import TelemetryConfig

logger = logging.getLogger(__name__)


def setup_telemetry(config: TelemetryConfig) -> None:
    """Initialize OpenTelemetry tracing and metrics.

    Exporter selection:
    - If OTEL_EXPORTER_OTLP_ENDPOINT env var is set, use OTLP regardless of config
    - config.exporter == "console" -> ConsoleSpanExporter / ConsoleMetricExporter
    - config.exporter == "otlp" -> OTLPSpanExporter / OTLPMetricExporter (requires otlp extra)
    - config.exporter == "none" or config.enabled == False -> no-op

    This function never raises — telemetry failure should not crash the server.
    """
    if not config.enabled:
        logger.info("Telemetry disabled by configuration")
        return

    try:
        _configure_providers(config)
    except Exception:
        logger.warning("Failed to initialize telemetry — continuing without it", exc_info=True)


def _configure_providers(config: TelemetryConfig) -> None:
    """Set up TracerProvider and MeterProvider with the appropriate exporters."""
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": config.service_name})

    # Determine exporter type: OTEL_EXPORTER_OTLP_ENDPOINT overrides config
    exporter_type = config.exporter
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        exporter_type = "otlp"

    if exporter_type == "none":
        logger.info("Telemetry exporter set to 'none' — no spans/metrics will be exported")
        return

    # Configure tracing
    span_exporter = _create_span_exporter(exporter_type, config)
    tracer_provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # Configure metrics
    metric_exporter = _create_metric_exporter(exporter_type, config)
    if metric_exporter is not None:
        metric_reader = PeriodicExportingMetricReader(metric_exporter)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    else:
        meter_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(meter_provider)

    logger.info("Telemetry initialized with %s exporter", exporter_type)


def _create_span_exporter(exporter_type: str, config: TelemetryConfig):  # type: ignore[no-untyped-def]
    """Create the appropriate span exporter."""
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    if exporter_type == "console":
        return ConsoleSpanExporter()

    if exporter_type == "otlp":
        return _create_otlp_span_exporter(config)

    logger.warning("Unknown exporter type '%s', falling back to console", exporter_type)
    return ConsoleSpanExporter()


def _create_metric_exporter(exporter_type: str, config: TelemetryConfig):  # type: ignore[no-untyped-def]
    """Create the appropriate metric exporter."""
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

    if exporter_type == "console":
        return ConsoleMetricExporter()

    if exporter_type == "otlp":
        return _create_otlp_metric_exporter(config)

    logger.warning("Unknown metric exporter type '%s', falling back to console", exporter_type)
    return ConsoleMetricExporter()


def _create_otlp_span_exporter(config: TelemetryConfig):  # type: ignore[no-untyped-def]
    """Create an OTLP span exporter. Requires the otlp optional extra."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", config.endpoint)

    if config.protocol == "http":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            return OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        except ImportError:
            logger.warning(
                "OTLP HTTP exporter not available. Install with: pip install agent-gateway[otlp]"
            )
            return None
    else:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            return OTLPSpanExporter(endpoint=endpoint)
        except ImportError:
            logger.warning(
                "OTLP gRPC exporter not available. Install with: pip install agent-gateway[otlp]"
            )
            return None


def _create_otlp_metric_exporter(config: TelemetryConfig):  # type: ignore[no-untyped-def]
    """Create an OTLP metric exporter. Requires the otlp optional extra."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", config.endpoint)

    if config.protocol == "http":
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

            return OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")
        except ImportError:
            logger.warning(
                "OTLP HTTP metric exporter not available. "
                "Install with: pip install agent-gateway[otlp]"
            )
            return None
    else:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )

            return OTLPMetricExporter(endpoint=endpoint)
        except ImportError:
            logger.warning(
                "OTLP gRPC metric exporter not available. "
                "Install with: pip install agent-gateway[otlp]"
            )
            return None
