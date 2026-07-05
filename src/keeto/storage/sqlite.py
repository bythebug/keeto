from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from keeto.core.span import Span, SpanEvent, SpanKind, SpanStatus, Trace


class SQLiteStorage:
    """Persistent SQLite storage backend using aiosqlite."""

    def __init__(self, path: str | Path = "./keeto.db") -> None:
        self._path = str(path)
        self._conn: Any = None  # aiosqlite.Connection
        self._lock = asyncio.Lock()

    async def _get_conn(self) -> Any:
        if self._conn is None:
            import aiosqlite

            self._conn = await aiosqlite.connect(self._path)
            self._conn.row_factory = aiosqlite.Row
            await self._ensure_schema()
        return self._conn

    async def _ensure_schema(self) -> None:
        conn = self._conn
        await conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS traces (
                trace_id   TEXT PRIMARY KEY,
                start_time TEXT NOT NULL,
                end_time   TEXT
            );

            CREATE TABLE IF NOT EXISTS spans (
                span_id          TEXT PRIMARY KEY,
                trace_id         TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
                parent_span_id   TEXT,
                name             TEXT NOT NULL,
                kind             TEXT NOT NULL,
                start_time       TEXT NOT NULL,
                end_time         TEXT,
                status           TEXT NOT NULL,
                status_message   TEXT,
                provider         TEXT,
                model            TEXT,
                input_tokens     INTEGER,
                output_tokens    INTEGER,
                cached_tokens    INTEGER,
                reasoning_tokens INTEGER,
                cost_usd         REAL,
                attributes       TEXT NOT NULL DEFAULT '{}',
                events           TEXT NOT NULL DEFAULT '[]'
            );

            CREATE INDEX IF NOT EXISTS spans_trace_id ON spans(trace_id);
        """)
        await conn.commit()

    async def append(self, span: Span) -> None:
        async with self._lock:
            conn = await self._get_conn()
            start_iso = span.start_time.isoformat()
            await conn.execute(
                """
                INSERT INTO traces (trace_id, start_time, end_time)
                VALUES (?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET end_time=excluded.end_time
                """,
                (
                    span.trace_id,
                    start_iso,
                    span.end_time.isoformat() if span.end_time else None,
                ),
            )
            attrs_json = json.dumps(span.attributes)
            events_json = json.dumps(
                [
                    {"name": e.name, "timestamp": e.timestamp.isoformat(), "attributes": e.attributes}
                    for e in span.events
                ]
            )
            await conn.execute(
                """
                INSERT OR REPLACE INTO spans (
                    span_id, trace_id, parent_span_id, name, kind,
                    start_time, end_time, status, status_message,
                    provider, model, input_tokens, output_tokens,
                    cached_tokens, reasoning_tokens, cost_usd,
                    attributes, events
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    span.span_id,
                    span.trace_id,
                    span.parent_span_id,
                    span.name,
                    span.kind.value,
                    span.start_time.isoformat(),
                    span.end_time.isoformat() if span.end_time else None,
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
                ),
            )
            await conn.commit()

    async def get_trace(self, trace_id: str) -> Trace | None:
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT trace_id, start_time, end_time FROM traces WHERE trace_id = ?",
                (trace_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            trace = _row_to_trace(row)
            async with conn.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time",
                (trace_id,),
            ) as cur:
                async for span_row in cur:
                    trace.add_span(_row_to_span(span_row))
            return trace

    async def list_traces(
        self,
        limit: int = 50,
        offset: int = 0,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Trace]:
        async with self._lock:
            conn = await self._get_conn()
            conditions: list[str] = []
            params: list[object] = []
            if since is not None:
                conditions.append("start_time >= ?")
                params.append(since.isoformat())
            if until is not None:
                conditions.append("start_time <= ?")
                params.append(until.isoformat())
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params += [limit, offset]
            query = (
                f"SELECT trace_id, start_time, end_time FROM traces "
                f"{where} ORDER BY start_time DESC LIMIT ? OFFSET ?"
            )
            async with conn.execute(query, params) as cur:
                trace_rows = await cur.fetchall()

            traces: list[Trace] = []
            for row in trace_rows:
                trace = _row_to_trace(row)
                async with conn.execute(
                    "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time",
                    (trace.trace_id,),
                ) as span_cur:
                    async for span_row in span_cur:
                        trace.add_span(_row_to_span(span_row))
                traces.append(trace)
            return traces

    async def purge(self, older_than: datetime) -> int:
        async with self._lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT COUNT(*) FROM traces WHERE start_time < ?",
                (older_than.isoformat(),),
            ) as cur:
                row = await cur.fetchone()
                count = row[0] if row else 0
            await conn.execute(
                "DELETE FROM traces WHERE start_time < ?",
                (older_than.isoformat(),),
            )
            await conn.commit()
            return count

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_trace(row: Any) -> Trace:
    start = _parse_dt(row["start_time"]) or datetime.now(timezone.utc)
    end = _parse_dt(row["end_time"])
    return Trace(trace_id=row["trace_id"], start_time=start, end_time=end)


def _row_to_span(row: Any) -> Span:
    attributes: dict[str, Any] = json.loads(row["attributes"] or "{}")
    raw_events: list[dict[str, Any]] = json.loads(row["events"] or "[]")
    events = [
        SpanEvent(
            name=e["name"],
            timestamp=_parse_dt(e["timestamp"]) or datetime.now(timezone.utc),
            attributes=e.get("attributes", {}),
        )
        for e in raw_events
    ]
    start = _parse_dt(row["start_time"]) or datetime.now(timezone.utc)
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
