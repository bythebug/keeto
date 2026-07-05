from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from keeto.core.span import Span, Trace


class TraceQuery(Protocol):
    """Filtering parameters for listing traces."""

    limit: int
    offset: int
    provider: str | None
    model: str | None
    has_error: bool | None
    since: datetime | None
    until: datetime | None


class AggResult(Protocol):
    """Aggregation result returned by storage.aggregate()."""

    total_cost_usd: float
    total_traces: int
    avg_latency_ms: float
    p95_latency_ms: float
    error_count: int
    data: dict[str, Any]


@runtime_checkable
class StorageBackend(Protocol):
    async def append(self, span: Span) -> None: ...

    async def get_trace(self, trace_id: str) -> Trace | None: ...

    async def list_traces(self, limit: int = 50, offset: int = 0) -> list[Trace]: ...

    async def purge(self, older_than: datetime) -> int: ...

    async def close(self) -> None: ...
