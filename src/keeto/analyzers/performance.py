"""Performance analysis utilities -- latency percentiles and anomaly detection."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

from keeto.core.span import SpanKind

if TYPE_CHECKING:
    from keeto.core.span import Span, Trace


@dataclass
class LatencyAnomaly:
    span: Span
    trace_id: str
    latency_ms: float
    session_mean_ms: float
    z_score: float


def detect_latency_anomalies(
    traces: list[Trace], z_threshold: float = 2.0
) -> list[LatencyAnomaly]:
    """Return LLM spans whose latency is more than z_threshold std-devs above the session mean."""
    items = [
        (s, t.trace_id, s.latency_ms)
        for t in traces
        for s in t.spans
        if s.kind == SpanKind.LLM and s.latency_ms is not None and s.latency_ms > 0
    ]
    if len(items) < 3:
        return []

    values = [lat for _, _, lat in items]
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return []

    return [
        LatencyAnomaly(
            span=s,
            trace_id=tid,
            latency_ms=lat,
            session_mean_ms=mean,
            z_score=(lat - mean) / stdev,
        )
        for s, tid, lat in items
        if (lat - mean) / stdev > z_threshold
    ]


def latency_percentiles(traces: list[Trace]) -> dict[str, float]:
    """Return P50/P95/P99 latency in ms across all LLM spans."""
    latencies = sorted(
        s.latency_ms
        for t in traces
        for s in t.spans
        if s.kind == SpanKind.LLM and s.latency_ms is not None
    )
    if not latencies:
        return {}

    def _pct(data: list[float], p: float) -> float:
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    return {
        "p50": _pct(latencies, 50),
        "p95": _pct(latencies, 95),
        "p99": _pct(latencies, 99),
        "min": latencies[0],
        "max": latencies[-1],
        "mean": statistics.mean(latencies),
    }


def throughput_per_minute(traces: list[Trace]) -> float | None:
    """Requests per minute based on trace start times."""
    times = sorted(t.start_time for t in traces if t.spans)
    if len(times) < 2:
        return None
    duration_minutes = (times[-1] - times[0]).total_seconds() / 60
    if duration_minutes <= 0:
        return None
    return len(times) / duration_minutes
