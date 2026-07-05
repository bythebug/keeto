"""Tests for bulk historical export with date range filter — issue #88."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from keeto.core.span import Span, SpanKind, SpanStatus
from keeto.storage.memory import MemoryStorage
from keeto.storage.sqlite import SQLiteStorage


def _make_span(trace_id: str, start: datetime, provider: str = "openai") -> Span:
    span = Span(
        trace_id=trace_id,
        span_id=trace_id[:16],
        name="chat",
        kind=SpanKind.LLM,
        start_time=start,
        provider=provider,
    )
    span.finish(status=SpanStatus.OK, end_time=start + timedelta(milliseconds=200))
    return span


BASE = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
SPANS = [_make_span(f"trace{i:02d}{'0' * 28}", BASE + timedelta(days=i)) for i in range(5)]


# ---------------------------------------------------------------------------
# MemoryStorage date range
# ---------------------------------------------------------------------------


class TestMemoryStorageDateRange:
    @pytest.fixture()
    async def storage(self) -> MemoryStorage:
        s = MemoryStorage()
        for sp in SPANS:
            await s.append(sp)
        return s

    async def test_since_filters(self, storage: MemoryStorage) -> None:
        since = BASE + timedelta(days=2)
        traces = await storage.list_traces(limit=100, since=since)
        assert len(traces) == 3  # days 2, 3, 4

    async def test_until_filters(self, storage: MemoryStorage) -> None:
        until = BASE + timedelta(days=2)
        traces = await storage.list_traces(limit=100, until=until)
        assert len(traces) == 3  # days 0, 1, 2

    async def test_since_and_until(self, storage: MemoryStorage) -> None:
        since = BASE + timedelta(days=1)
        until = BASE + timedelta(days=3)
        traces = await storage.list_traces(limit=100, since=since, until=until)
        assert len(traces) == 3  # days 1, 2, 3

    async def test_no_filter_returns_all(self, storage: MemoryStorage) -> None:
        traces = await storage.list_traces(limit=100)
        assert len(traces) == 5

    async def test_empty_range_returns_empty(self, storage: MemoryStorage) -> None:
        far_future = BASE + timedelta(days=100)
        traces = await storage.list_traces(limit=100, since=far_future)
        assert traces == []


# ---------------------------------------------------------------------------
# SQLiteStorage date range
# ---------------------------------------------------------------------------


class TestSQLiteStorageDateRange:
    @pytest.fixture()
    async def storage(self, tmp_path: Path) -> SQLiteStorage:
        s = SQLiteStorage(tmp_path / "test.db")
        for sp in SPANS:
            await s.append(sp)
        return s

    async def test_since_filters(self, storage: SQLiteStorage) -> None:
        since = BASE + timedelta(days=2)
        traces = await storage.list_traces(limit=100, since=since)
        assert len(traces) == 3

    async def test_until_filters(self, storage: SQLiteStorage) -> None:
        until = BASE + timedelta(days=2)
        traces = await storage.list_traces(limit=100, until=until)
        assert len(traces) == 3

    async def test_since_and_until(self, storage: SQLiteStorage) -> None:
        since = BASE + timedelta(days=1)
        until = BASE + timedelta(days=3)
        traces = await storage.list_traces(limit=100, since=since, until=until)
        assert len(traces) == 3

    async def test_no_filter(self, storage: SQLiteStorage) -> None:
        traces = await storage.list_traces(limit=100)
        assert len(traces) == 5


# ---------------------------------------------------------------------------
# monitor.export() with date range (end-to-end)
# Sync tests — monitor.export() uses asyncio.run() internally which can't be
# called from an already-running event loop.
# ---------------------------------------------------------------------------


class TestMonitorExportDateRange:
    def _populated_monitor(self) -> Monitor:  # type: ignore[name-defined]  # noqa: F821
        from keeto.core.monitor import Monitor

        async def _populate(storage: MemoryStorage) -> None:
            for sp in SPANS:
                await storage.append(sp)

        mon = Monitor(storage=MemoryStorage(), auto=False)
        mon.start()
        asyncio.run(_populate(mon._storage))
        return mon

    def test_export_json_with_since(self, tmp_path: Path) -> None:
        mon = self._populated_monitor()
        out = str(tmp_path / "out.json")
        mon.export(out, since=BASE + timedelta(days=3))
        data = json.loads(Path(out).read_text())
        assert len(data) == 2  # days 3 and 4
        mon.stop()

    def test_export_with_string_dates(self, tmp_path: Path) -> None:
        mon = self._populated_monitor()
        out = str(tmp_path / "out.json")
        # BASE is Jan 15; +3 days = Jan 18; spans on Jan 18 and 19
        mon.export(out, since="2024-01-18T12:00:00+00:00")
        data = json.loads(Path(out).read_text())
        assert len(data) == 2
        mon.stop()

    def test_export_with_until(self, tmp_path: Path) -> None:
        mon = self._populated_monitor()
        out = str(tmp_path / "out.json")
        mon.export(out, until=BASE + timedelta(days=1))
        data = json.loads(Path(out).read_text())
        assert len(data) == 2  # days 0 and 1
        mon.stop()
