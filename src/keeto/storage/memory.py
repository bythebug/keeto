from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime

from keeto.core.span import Span, Trace


class MemoryStorage:
    """
    In-memory ring buffer. Default storage backend — zero dependencies.

    Traces are grouped by trace_id. Once `max_traces` is exceeded the oldest
    trace is evicted, so memory stays bounded regardless of run duration.
    """

    def __init__(self, max_traces: int = 1000) -> None:
        self._max_traces = max_traces
        self._traces: dict[str, Trace] = {}
        self._order: deque[str] = deque()
        self._lock = asyncio.Lock()

    async def append(self, span: Span) -> None:
        async with self._lock:
            if span.trace_id not in self._traces:
                if len(self._order) >= self._max_traces:
                    oldest = self._order.popleft()
                    self._traces.pop(oldest, None)
                new_trace = Trace(trace_id=span.trace_id)
                new_trace.start_time = span.start_time
                self._traces[span.trace_id] = new_trace
                self._order.append(span.trace_id)
            self._traces[span.trace_id].add_span(span)

    async def get_trace(self, trace_id: str) -> Trace | None:
        async with self._lock:
            return self._traces.get(trace_id)

    async def list_traces(
        self,
        limit: int = 50,
        offset: int = 0,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Trace]:
        async with self._lock:
            ids = list(reversed(self._order))
            filtered = [
                self._traces[tid]
                for tid in ids
                if tid in self._traces
                and (since is None or self._traces[tid].start_time >= since)
                and (until is None or self._traces[tid].start_time <= until)
            ]
            return filtered[offset : offset + limit]

    async def purge(self, older_than: datetime) -> int:
        async with self._lock:
            to_delete = [
                tid
                for tid, trace in self._traces.items()
                if trace.start_time < older_than
            ]
            for tid in to_delete:
                del self._traces[tid]
                try:
                    self._order.remove(tid)
                except ValueError:
                    pass
            return len(to_delete)

    async def close(self) -> None:
        pass

    def __len__(self) -> int:
        return len(self._traces)
