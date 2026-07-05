"""PostgreSQL storage backend — issue #87.

Requires ``keeto[postgres]`` (asyncpg driver).

Usage::

    from keeto import Monitor
    from keeto.storage.postgres import PostgresStorage

    monitor = Monitor(storage=PostgresStorage("postgresql://localhost/keeto"))
    monitor.start()
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from keeto.core.span import Span, SpanEvent, SpanKind, SpanStatus, Trace


class PostgresStorage:
    """Persistent PostgreSQL storage backend using asyncpg.

    Connection pooling is handled automatically.  Suitable for multi-process
    or team deployments.
    """

    def __init__(
        self,
        dsn: str = "postgresql://localhost/keeto",
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Any = None  # asyncpg.Pool

    async def _get_pool(self) -> Any:
        if self._pool is None:
            try:
                import asyncpg  # type: ignore[import-untyped]
            except ImportError as exc:
                raise ImportError(
                    "PostgreSQL storage requires keeto[postgres]. Install with: pip install keeto[postgres]"
                ) from exc
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
            )
            await self._ensure_schema()
        return self._pool

    async def _ensure_schema(self) -> None:
        pool = self._pool
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS keeto_traces (
                    trace_id   TEXT PRIMARY KEY,
                    start_time TIMESTAMPTZ NOT NULL,
                    end_time   TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS keeto_spans (
                    span_id          TEXT PRIMARY KEY,
                    trace_id         TEXT NOT NULL REFERENCES keeto_traces(trace_id) ON DELETE CASCADE,
                    parent_span_id   TEXT,
                    name             TEXT NOT NULL,
                    kind             TEXT NOT NULL,
                    start_time       TIMESTAMPTZ NOT NULL,
                    end_time         TIMESTAMPTZ,
                    status           TEXT NOT NULL,
                    status_message   TEXT,
                    provider         TEXT,
                    model            TEXT,
                    input_tokens     INTEGER,
                    output_tokens    INTEGER,
                    cached_tokens    INTEGER,
                    reasoning_tokens INTEGER,
                    cost_usd         DOUBLE PRECISION,
                    attributes       JSONB NOT NULL DEFAULT '{}',
                    events           JSONB NOT NULL DEFAULT '[]'
                );

                CREATE INDEX IF NOT EXISTS keeto_spans_trace_id ON keeto_spans(trace_id);
                CREATE INDEX IF NOT EXISTS keeto_traces_start_time ON keeto_traces(start_time);
            """)

    async def append(self, span: Span) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                    INSERT INTO keeto_traces (trace_id, start_time, end_time)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (trace_id) DO UPDATE
                        SET end_time = EXCLUDED.end_time
                    """,
                span.trace_id,
                span.start_time,
                span.end_time,
            )
            attrs_json = json.dumps(span.attributes)
            events_json = json.dumps(
                [
                    {
                        "name": e.name,
                        "timestamp": e.timestamp.isoformat(),
                        "attributes": e.attributes,
                    }
                    for e in span.events
                ]
            )
            await conn.execute(
                """
                    INSERT INTO keeto_spans (
                        span_id, trace_id, parent_span_id, name, kind,
                        start_time, end_time, status, status_message,
                        provider, model, input_tokens, output_tokens,
                        cached_tokens, reasoning_tokens, cost_usd,
                        attributes, events
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18
                    )
                    ON CONFLICT (span_id) DO UPDATE SET
                        end_time       = EXCLUDED.end_time,
                        status         = EXCLUDED.status,
                        status_message = EXCLUDED.status_message,
                        input_tokens   = EXCLUDED.input_tokens,
                        output_tokens  = EXCLUDED.output_tokens,
                        cached_tokens  = EXCLUDED.cached_tokens,
                        cost_usd       = EXCLUDED.cost_usd,
                        attributes     = EXCLUDED.attributes,
                        events         = EXCLUDED.events
                    """,
                span.span_id,
                span.trace_id,
                span.parent_span_id,
                span.name,
                span.kind.value,
                span.start_time,
                span.end_time,
                span.status.value,
                span.status_message,
                span.provider,
                span.model,
                span.input_tokens,
                span.output_tokens,
                span.cached_tokens,
                span.reasoning_tokens,
                span.cost_usd,
                attrs_json,
                events_json,
            )

    async def get_trace(self, trace_id: str) -> Trace | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT trace_id, start_time, end_time FROM keeto_traces WHERE trace_id = $1",
                trace_id,
            )
            if row is None:
                return None
            trace = _row_to_trace(row)
            span_rows = await conn.fetch(
                "SELECT * FROM keeto_spans WHERE trace_id = $1 ORDER BY start_time",
                trace_id,
            )
            for sr in span_rows:
                trace.add_span(_row_to_span(sr))
            return trace

    async def list_traces(
        self,
        limit: int = 50,
        offset: int = 0,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Trace]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            conditions = []
            args: list[Any] = []
            arg_idx = 1
            if since is not None:
                conditions.append(f"start_time >= ${arg_idx}")
                args.append(since)
                arg_idx += 1
            if until is not None:
                conditions.append(f"start_time <= ${arg_idx}")
                args.append(until)
                arg_idx += 1

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            args += [limit, offset]
            query = (
                f"SELECT trace_id, start_time, end_time FROM keeto_traces "
                f"{where} ORDER BY start_time DESC "
                f"LIMIT ${arg_idx} OFFSET ${arg_idx + 1}"
            )
            trace_rows = await conn.fetch(query, *args)

            traces: list[Trace] = []
            for tr in trace_rows:
                trace = _row_to_trace(tr)
                span_rows = await conn.fetch(
                    "SELECT * FROM keeto_spans WHERE trace_id = $1 ORDER BY start_time",
                    trace.trace_id,
                )
                for sr in span_rows:
                    trace.add_span(_row_to_span(sr))
                traces.append(trace)
            return traces

    async def purge(self, older_than: datetime) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM keeto_traces WHERE start_time < $1",
                older_than,
            )
            # asyncpg returns "DELETE N"
            try:
                return int(result.split()[-1])
            except (ValueError, IndexError):
                return 0

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


# ---------------------------------------------------------------------------
# Row → model helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _row_to_trace(row: Any) -> Trace:
    start = _parse_dt(row["start_time"]) or datetime.now(UTC)
    end = _parse_dt(row["end_time"])
    return Trace(trace_id=row["trace_id"], start_time=start, end_time=end)


def _row_to_span(row: Any) -> Span:
    attrs_raw = row["attributes"]
    attributes: dict[str, Any] = json.loads(attrs_raw) if isinstance(attrs_raw, str) else (attrs_raw or {})
    events_raw = row["events"]
    raw_events: list[dict[str, Any]] = json.loads(events_raw) if isinstance(events_raw, str) else (events_raw or [])
    events = [
        SpanEvent(
            name=e["name"],
            timestamp=_parse_dt(e["timestamp"]) or datetime.now(UTC),
            attributes=e.get("attributes", {}),
        )
        for e in raw_events
    ]
    start = _parse_dt(row["start_time"]) or datetime.now(UTC)
    end = _parse_dt(row["end_time"])
    return Span(
        span_id=row["span_id"],
        trace_id=row["trace_id"],
        parent_span_id=row["parent_span_id"],
        name=row["name"],
        kind=SpanKind(row["kind"]),
        start_time=start,
        end_time=end,
        status=SpanStatus(row["status"]),
        status_message=row["status_message"],
        provider=row["provider"],
        model=row["model"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cached_tokens=row["cached_tokens"],
        reasoning_tokens=row["reasoning_tokens"],
        cost_usd=row["cost_usd"],
        attributes=attributes,
        events=events,
    )
