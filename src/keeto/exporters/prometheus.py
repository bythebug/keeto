"""Prometheus metrics exporter — issue #85.

Generates Prometheus text-format metrics from Keeto traces.

Two modes:
1. ``generate_prometheus_text(traces)`` — pure function, no external deps.
2. ``PrometheusExporter`` — optionally uses ``prometheus_client`` for a
   proper ``/metrics`` endpoint that increments counters in real time.

The web dashboard mounts a ``/metrics`` route that calls
``generate_prometheus_text``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from keeto.core.span import SpanStatus, Trace


def generate_prometheus_text(traces: list[Trace]) -> str:
    """Aggregate *traces* and return Prometheus text-format metrics (no deps)."""
    # counters indexed by (provider, model, status)
    req_count: dict[tuple[str, str, str], int] = defaultdict(int)
    # latency buckets (ms): sum and count
    lat_sum: dict[tuple[str, str], float] = defaultdict(float)
    lat_count: dict[tuple[str, str], int] = defaultdict(int)
    # tokens indexed by (provider, model, type)
    tokens: dict[tuple[str, str, str], int] = defaultdict(int)
    # cost indexed by (provider, model)
    cost: dict[tuple[str, str], float] = defaultdict(float)
    # errors indexed by (provider, model)
    errors: dict[tuple[str, str], int] = defaultdict(int)

    for trace in traces:
        for span in trace.spans:
            p = span.provider or "unknown"
            m = span.model or "unknown"
            s = span.status.value

            req_count[(p, m, s)] += 1

            if span.latency_ms is not None:
                lat_sum[(p, m)] += span.latency_ms / 1000.0
                lat_count[(p, m)] += 1

            if span.input_tokens is not None:
                tokens[(p, m, "input")] += span.input_tokens
            if span.output_tokens is not None:
                tokens[(p, m, "output")] += span.output_tokens

            if span.cost_usd is not None:
                cost[(p, m)] += span.cost_usd

            if span.status == SpanStatus.ERROR:
                errors[(p, m)] += 1

    lines: list[str] = []

    # keeto_requests_total
    lines.append("# HELP keeto_requests_total Total AI requests captured by Keeto")
    lines.append("# TYPE keeto_requests_total counter")
    for (p, m, st), cnt in sorted(req_count.items()):
        lines.append(f'keeto_requests_total{{provider="{p}",model="{m}",status="{st}"}} {cnt}')

    # keeto_request_duration_seconds
    lines.append("# HELP keeto_request_duration_seconds AI request latency in seconds")
    lines.append("# TYPE keeto_request_duration_seconds summary")
    for (p, m), s in sorted(lat_sum.items()):
        cnt = lat_count[(p, m)]
        lines.append(f'keeto_request_duration_seconds_sum{{provider="{p}",model="{m}"}} {s:.6f}')
        lines.append(f'keeto_request_duration_seconds_count{{provider="{p}",model="{m}"}} {cnt}')

    # keeto_tokens_total
    lines.append("# HELP keeto_tokens_total Total tokens processed")
    lines.append("# TYPE keeto_tokens_total counter")
    for (p, m, t), n in sorted(tokens.items()):
        lines.append(f'keeto_tokens_total{{provider="{p}",model="{m}",type="{t}"}} {n}')

    # keeto_cost_usd_total
    lines.append("# HELP keeto_cost_usd_total Total estimated cost in USD")
    lines.append("# TYPE keeto_cost_usd_total counter")
    for (p, m), c in sorted(cost.items()):
        lines.append(f'keeto_cost_usd_total{{provider="{p}",model="{m}"}} {c:.8f}')

    # keeto_errors_total
    lines.append("# HELP keeto_errors_total Total error spans")
    lines.append("# TYPE keeto_errors_total counter")
    for (p, m), n in sorted(errors.items()):
        lines.append(f'keeto_errors_total{{provider="{p}",model="{m}"}} {n}')

    return "\n".join(lines) + "\n"


class PrometheusExporter:
    """Real-time Prometheus exporter using ``prometheus_client``.

    Install ``prometheus_client`` (not a keeto dep by default)::

        pip install prometheus_client

    Then serve via the web dashboard ``/metrics`` endpoint, or start a
    standalone HTTP server::

        exporter = PrometheusExporter()
        exporter.start_server(port=9090)
    """

    def __init__(self) -> None:
        try:
            import prometheus_client  # type: ignore[import-untyped]

            self._pc = prometheus_client
        except ImportError:
            self._pc = None

        self._requests_total: Any = None
        self._duration: Any = None
        self._tokens_total: Any = None
        self._cost_total: Any = None
        self._errors_total: Any = None
        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized or self._pc is None:
            return
        pc = self._pc
        self._requests_total = pc.Counter(
            "keeto_requests_total",
            "Total AI requests captured by Keeto",
            ["provider", "model", "status"],
        )
        self._duration = pc.Histogram(
            "keeto_request_duration_seconds",
            "AI request latency in seconds",
            ["provider", "model"],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, float("inf")],
        )
        self._tokens_total = pc.Counter(
            "keeto_tokens_total",
            "Total tokens processed",
            ["provider", "model", "type"],
        )
        self._cost_total = pc.Counter(
            "keeto_cost_usd_total",
            "Total estimated cost in USD",
            ["provider", "model"],
        )
        self._errors_total = pc.Counter(
            "keeto_errors_total",
            "Total error spans",
            ["provider", "model"],
        )
        self._initialized = True

    def record_span(self, span: Any) -> None:
        """Increment counters for a single completed span."""
        self._ensure_init()
        if self._pc is None or not self._initialized:
            return
        p = span.provider or "unknown"
        m = span.model or "unknown"
        self._requests_total.labels(p, m, span.status.value).inc()  # type: ignore[union-attr]
        if span.latency_ms is not None:
            self._duration.labels(p, m).observe(span.latency_ms / 1000.0)  # type: ignore[union-attr]
        if span.input_tokens:
            self._tokens_total.labels(p, m, "input").inc(span.input_tokens)  # type: ignore[union-attr]
        if span.output_tokens:
            self._tokens_total.labels(p, m, "output").inc(span.output_tokens)  # type: ignore[union-attr]
        if span.cost_usd:
            self._cost_total.labels(p, m).inc(span.cost_usd)  # type: ignore[union-attr]
        if span.status == SpanStatus.ERROR:
            self._errors_total.labels(p, m).inc()  # type: ignore[union-attr]

    def generate_latest(self) -> str:
        """Return current prometheus_client metrics as text (requires package)."""
        if self._pc is None:
            return "# prometheus_client not installed\n"
        return self._pc.generate_latest().decode()

    def start_server(self, port: int = 9090) -> None:
        """Start a standalone Prometheus metrics HTTP server on *port*."""
        if self._pc is None:
            raise ImportError("prometheus_client not installed. Run: pip install prometheus_client")
        self._ensure_init()
        self._pc.start_http_server(port)
