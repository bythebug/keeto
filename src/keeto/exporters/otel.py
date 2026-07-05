"""OpenTelemetry OTLP exporter — requires keeto[otel].

Issues #81 (OTLP exporter) and #82 (Jaeger via OTLP).

Converts Keeto Span/Trace objects to OTel ReadableSpans and ships them to any
OTLP-compatible collector (Jaeger, Tempo, OpenTelemetry Collector, etc.).

Usage:
    monitor.export(format="otel", endpoint="http://localhost:4317")
    monitor.export(format="otel", endpoint="http://jaeger:4317", protocol="grpc")
    monitor.export(format="otel", endpoint="http://localhost:4318", protocol="http")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from keeto.core.span import SpanStatus, Trace

if TYPE_CHECKING:
    from keeto.core.span import Span


def _ns(dt: Any) -> int:
    """Convert datetime to nanoseconds since epoch."""
    return int(dt.timestamp() * 1_000_000_000)


def _trace_id_int(tid: str) -> int:
    return int(tid.ljust(32, "0")[:32], 16)


def _span_id_int(sid: str) -> int:
    return int(sid.ljust(16, "0")[:16], 16)


def _to_otel_span(span: "Span", resource: Any) -> Any:
    """Convert a Keeto Span to an OTel ReadableSpan."""
    from opentelemetry.sdk.instrumentation import InstrumentationScope
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.trace import SpanContext, SpanKind as OtelSpanKind, TraceFlags
    from opentelemetry.trace.status import Status, StatusCode

    ctx = SpanContext(
        trace_id=_trace_id_int(span.trace_id),
        span_id=_span_id_int(span.span_id),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    parent_ctx: SpanContext | None = None
    if span.parent_span_id:
        parent_ctx = SpanContext(
            trace_id=_trace_id_int(span.trace_id),
            span_id=_span_id_int(span.parent_span_id),
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )

    _code_map = {
        SpanStatus.OK: StatusCode.OK,
        SpanStatus.ERROR: StatusCode.ERROR,
        SpanStatus.UNSET: StatusCode.UNSET,
    }
    status = Status(_code_map.get(span.status, StatusCode.UNSET), span.status_message or "")

    # GenAI semantic conventions (OTel 1.26+)
    attrs: dict[str, str | int | float | bool] = {}
    if span.provider:
        attrs["gen_ai.system"] = span.provider
    if span.model:
        attrs["gen_ai.request.model"] = span.model
    if span.input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = span.input_tokens
    if span.output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = span.output_tokens
    if span.cached_tokens is not None:
        attrs["gen_ai.usage.cached_tokens"] = span.cached_tokens
    if span.cost_usd is not None:
        attrs["keeto.cost_usd"] = span.cost_usd
    for k, v in span.attributes.items():
        if isinstance(v, (str, int, float, bool)):
            attrs[k] = v
        else:
            attrs[k] = str(v)

    start_ns = _ns(span.start_time)
    end_ns = _ns(span.end_time) if span.end_time else None
    scope = InstrumentationScope(name="keeto", version="0.5.0")

    events: list[Any] = []
    try:
        import opentelemetry.sdk.trace as _sdk
        OtelEvent = getattr(_sdk, "Event", None)
        if OtelEvent is not None:
            for ev in span.events:
                ev_attrs = {
                    k: v
                    for k, v in ev.attributes.items()
                    if isinstance(v, (str, int, float, bool))
                }
                events.append(
                    OtelEvent(name=ev.name, attributes=ev_attrs, timestamp=_ns(ev.timestamp))
                )
    except Exception:
        events = []

    return ReadableSpan(
        name=span.name,
        context=ctx,
        parent=parent_ctx,
        resource=resource,
        attributes=attrs,
        events=events,
        links=(),
        kind=OtelSpanKind.INTERNAL,
        instrumentation_scope=scope,
        status=status,
        start_time=start_ns,
        end_time=end_ns,
    )


def export_otel(
    traces: list[Trace],
    endpoint: str = "http://localhost:4317",
    protocol: str = "grpc",
    service_name: str = "keeto",
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> None:
    """Export traces to an OTLP endpoint (Jaeger, Tempo, OTel Collector, …).

    :param endpoint: Collector endpoint URL.
    :param protocol: ``"grpc"`` (default) or ``"http"``.
    :param service_name: OTel ``service.name`` resource attribute.
    :param headers: Extra HTTP/gRPC headers (e.g. auth tokens).

    Jaeger (≥1.35) accepts OTLP natively — just point at port 4317::

        monitor.export(format="otel", endpoint="http://jaeger:4317")
    """
    try:
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace.export import SpanExportResult
    except ImportError as exc:
        raise ImportError(
            "OTLP export requires keeto[otel]. Install with: pip install keeto[otel]"
        ) from exc

    resource = Resource.create({SERVICE_NAME: service_name})
    otel_spans = [_to_otel_span(span, resource) for trace in traces for span in trace.spans]
    if not otel_spans:
        return

    exporter: Any
    if protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers or {})
    elif protocol == "http":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter as HttpExporter,
            )
        except ImportError as exc:
            raise ImportError(
                "HTTP OTLP export requires opentelemetry-exporter-otlp-proto-http. "
                "Install: pip install opentelemetry-exporter-otlp-proto-http"
            ) from exc
        url = endpoint.rstrip("/")
        if not url.endswith("/v1/traces"):
            url = f"{url}/v1/traces"
        exporter = HttpExporter(endpoint=url, headers=headers or {})
    else:
        raise ValueError(f"Unknown OTLP protocol: {protocol!r}. Use 'grpc' or 'http'.")

    try:
        result = exporter.export(otel_spans)
    finally:
        exporter.shutdown()

    if result != SpanExportResult.SUCCESS:
        raise RuntimeError(f"OTLP export failed with status: {result}")
