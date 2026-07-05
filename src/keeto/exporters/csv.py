from __future__ import annotations

import csv
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keeto.core.span import Trace

_FIELDS = [
    "trace_id",
    "provider",
    "model",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "cost_usd",
    "has_error",
    "start_time",
]


def export_csv(traces: list[Trace], path: str | None = None) -> None:
    out = open(path, "w", newline="", encoding="utf-8") if path else sys.stdout  # noqa: SIM115
    try:
        writer = csv.DictWriter(out, fieldnames=_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for trace in traces:
            writer.writerow(
                {
                    "trace_id": trace.trace_id,
                    "provider": trace.provider or "",
                    "model": trace.model or "",
                    "latency_ms": trace.latency_ms or "",
                    "input_tokens": trace.total_input_tokens,
                    "output_tokens": trace.total_output_tokens,
                    "cached_tokens": sum(s.cached_tokens for s in trace.spans if s.cached_tokens),
                    "cost_usd": trace.total_cost_usd,
                    "has_error": trace.has_error,
                    "start_time": trace.start_time.isoformat(),
                }
            )
    finally:
        if path:
            out.close()
