"""Error pattern detection and clustering."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from keeto.core.span import SpanStatus, Trace


@dataclass
class ErrorCluster:
    pattern: str
    count: int
    trace_ids: list[str] = field(default_factory=list)
    example_message: str = ""


def cluster_errors(traces: list[Trace]) -> list[ErrorCluster]:
    """Group error spans by their error pattern (type prefix or status_message prefix)."""
    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for trace in traces:
        for span in trace.spans:
            if span.status != SpanStatus.ERROR:
                continue
            msg = span.status_message or ""
            pattern = _extract_pattern(msg)
            buckets[pattern].append((trace.trace_id, msg))

    clusters = [
        ErrorCluster(
            pattern=pattern,
            count=len(entries),
            trace_ids=[tid for tid, _ in entries[:10]],
            example_message=entries[0][1] if entries else "",
        )
        for pattern, entries in buckets.items()
    ]
    return sorted(clusters, key=lambda c: -c.count)


def _extract_pattern(message: str) -> str:
    """Extract a short stable pattern from an error message for grouping."""
    if not message:
        return "unknown_error"
    # Try to extract exception type from "ExcType: message" format
    if ":" in message:
        candidate = message.split(":")[0].strip()
        # Looks like an exception class name if it's CamelCase or has "Error"/"Exception"
        if len(candidate) < 60 and (" " not in candidate or "Error" in candidate):
            return candidate
    # Fall back to first 50 chars
    return message[:50].strip()
