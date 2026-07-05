"""Tests for the TUI app skeleton and trace list widget."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest
from keeto.core.span import Span, SpanStatus, Trace
from keeto.dashboard.tui.app import KeetoApp
from keeto.dashboard.tui.widgets.cost import CostView
from keeto.dashboard.tui.widgets.errors import ErrorsView
from keeto.dashboard.tui.widgets.performance import PerformanceView
from keeto.dashboard.tui.widgets._utils import _age, _fmt_cost, _fmt_lat, _fmt_tokens
from keeto.dashboard.tui.widgets.traces import TraceListWidget, TracesView
from keeto.storage.memory import MemoryStorage


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def _make_trace(
    trace_id: str = "abc123",
    provider: str = "openai",
    model: str = "gpt-4o",
    latency_ms: float = 500.0,
    input_tokens: int = 200,
    output_tokens: int = 80,
    cost_usd: float = 0.0012,
    error: bool = False,
) -> Trace:
    trace = Trace(trace_id=trace_id)
    span = Span(
        trace_id=trace_id,
        span_id="s1",
        name=f"{provider}.chat",
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    span.finish(status=SpanStatus.ERROR if error else SpanStatus.OK)
    span.end_time = span.start_time + timedelta(milliseconds=latency_ms)
    trace.add_span(span)
    return trace


class TestKeetoApp:
    def test_instantiates(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        assert app.TITLE == "keeto"

    def test_has_expected_bindings(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        keys = {b.key for b in app.BINDINGS}
        assert "q" in keys
        assert "r" in keys
        assert "/" in keys

    def test_refresh_interval_positive(self) -> None:
        from keeto.dashboard.tui.app import _REFRESH_INTERVAL
        assert _REFRESH_INTERVAL > 0

    @pytest.mark.asyncio
    async def test_compose_runs(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            assert app.query_one(TracesView) is not None
            assert app.query_one(CostView) is not None
            assert app.query_one(PerformanceView) is not None
            assert app.query_one(ErrorsView) is not None

    @pytest.mark.asyncio
    async def test_quit_action(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            await pilot.press("q")


class TestTraceListWidget:
    @pytest.mark.asyncio
    async def test_columns_rendered(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            table = widget.query_one("DataTable")
            assert len(table.columns) == len(TraceListWidget._COLUMNS)

    @pytest.mark.asyncio
    async def test_update_adds_rows(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        traces = [_make_trace(f"t{i}") for i in range(5)]
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update(traces)
            await pilot.pause()
            assert widget.query_one("DataTable").row_count == 5

    @pytest.mark.asyncio
    async def test_update_removes_stale_rows(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update([_make_trace("t1"), _make_trace("t2")])
            await pilot.pause()
            widget.update([_make_trace("t1")])  # t2 removed
            await pilot.pause()
            assert widget.query_one("DataTable").row_count == 1

    @pytest.mark.asyncio
    async def test_refresh_preserves_cursor(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        traces = [_make_trace(f"t{i}") for i in range(3)]
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update(traces)
            await pilot.pause()
            table = widget.query_one("DataTable")
            table.move_cursor(row=1)
            row_before = table.cursor_row
            # Refresh with same traces
            widget.update(traces)
            await pilot.pause()
            assert table.cursor_row == row_before


class TestFormatHelpers:
    def test_fmt_lat_ms(self) -> None:
        assert _fmt_lat(450.0) == "450ms"

    def test_fmt_lat_seconds(self) -> None:
        assert _fmt_lat(1500.0) == "1.50s"

    def test_fmt_lat_none(self) -> None:
        assert _fmt_lat(None) == "—"

    def test_fmt_tokens_thousands(self) -> None:
        assert _fmt_tokens(2500) == "2.5k"

    def test_fmt_tokens_zero(self) -> None:
        assert _fmt_tokens(0) == "—"

    def test_fmt_cost_zero(self) -> None:
        assert _fmt_cost(0.0) == "—"

    def test_fmt_cost_normal(self) -> None:
        assert _fmt_cost(0.0032) == "$0.0032"

    def test_age_seconds(self) -> None:
        from datetime import datetime, timezone
        dt = datetime.now(timezone.utc) - timedelta(seconds=30)
        assert "s ago" in _age(dt)

    def test_age_minutes(self) -> None:
        from datetime import datetime, timezone
        dt = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert "m ago" in _age(dt)


class TestTimeline:
    def test_single_span_produces_one_line(self) -> None:
        from keeto.dashboard.tui.widgets.timeline import build_waterfall
        trace = _make_trace("t1", latency_ms=500.0)
        lines = build_waterfall(trace, bar_cols=40).splitlines()
        assert len(lines) == 1

    def test_bar_contains_block_char(self) -> None:
        from keeto.dashboard.tui.widgets.timeline import build_waterfall, _BAR_CHAR
        trace = _make_trace("t1", latency_ms=500.0)
        result = build_waterfall(trace, bar_cols=40)
        assert _BAR_CHAR in result

    def test_no_spans_returns_placeholder(self) -> None:
        from keeto.dashboard.tui.widgets.timeline import build_waterfall
        trace = Trace(trace_id="empty")
        result = build_waterfall(trace)
        assert "no spans" in result

    def test_multiple_spans_multiple_lines(self) -> None:
        from datetime import timedelta
        from keeto.dashboard.tui.widgets.timeline import build_waterfall
        from keeto.core.span import Span, SpanStatus
        trace = Trace(trace_id="multi")
        for i in range(3):
            sp = Span(trace_id="multi", span_id=f"s{i}", name=f"span{i}")
            sp.finish()
            trace.add_span(sp)
        result = build_waterfall(trace, bar_cols=40)
        assert len(result.splitlines()) == 3

    def test_latency_shown_in_output(self) -> None:
        from keeto.dashboard.tui.widgets.timeline import build_waterfall
        trace = _make_trace("t1", latency_ms=750.0)
        result = build_waterfall(trace, bar_cols=40)
        assert "750ms" in result
