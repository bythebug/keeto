"""Cost analysis utilities -- anomaly detection and aggregation."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keeto.core.span import Span, Trace


@dataclass
class CostAnomaly:
    span: Span
    trace_id: str
    cost_usd: float
    session_mean_usd: float
    z_score: float


def detect_cost_anomalies(traces: list[Trace], z_threshold: float = 2.0) -> list[CostAnomaly]:
    """Return spans whose cost is more than z_threshold std-devs above the session mean."""
    items = [(s, t.trace_id, s.cost_usd) for t in traces for s in t.spans if s.cost_usd is not None and s.cost_usd > 0]
    if len(items) < 3:
        return []

    values = [c for _, _, c in items]
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return []

    return [
        CostAnomaly(
            span=s,
            trace_id=tid,
            cost_usd=c,
            session_mean_usd=mean,
            z_score=(c - mean) / stdev,
        )
        for s, tid, c in items
        if (c - mean) / stdev > z_threshold
    ]


def aggregate_cost_by_model(traces: list[Trace]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for trace in traces:
        for span in trace.spans:
            if span.model and span.cost_usd is not None:
                totals[span.model] = totals.get(span.model, 0.0) + span.cost_usd
    return dict(sorted(totals.items(), key=lambda x: -x[1]))


def aggregate_cost_by_provider(traces: list[Trace]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for trace in traces:
        for span in trace.spans:
            if span.provider and span.cost_usd is not None:
                totals[span.provider] = totals.get(span.provider, 0.0) + span.cost_usd
    return dict(sorted(totals.items(), key=lambda x: -x[1]))
