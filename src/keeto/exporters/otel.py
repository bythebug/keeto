"""OpenTelemetry OTLP exporter — requires keeto[otel]."""

from __future__ import annotations

from keeto.core.span import Trace


def export_otel(traces: list[Trace], endpoint: str = "http://localhost:4317", **kwargs: object) -> None:
    try:
        from opentelemetry import trace as otel_trace  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "OpenTelemetry export requires keeto[otel]. "
            "Install with: pip install keeto[otel]"
        ) from exc

    # Full OTEL export implementation in issue #81
    raise NotImplementedError("OTEL export is planned for v0.5 (issue #81).")
