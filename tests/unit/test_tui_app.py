"""Tests for the TUI app skeleton and trace list widget."""

from __future__ import annotations

from datetime import UTC, timedelta

import pytest

from keeto.core.span import Span, SpanStatus, Trace
from keeto.dashboard.tui.app import KeetoApp
from keeto.dashboard.tui.widgets._utils import _age, _fmt_cost, _fmt_lat, _fmt_tokens
from keeto.dashboard.tui.widgets.cost import CostView
from keeto.dashboard.tui.widgets.errors import ErrorsView
from keeto.dashboard.tui.widgets.performance import PerformanceView
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
        assert "d" in keys  # dark/light toggle (#39)

    @pytest.mark.asyncio
    async def test_toggle_dark_flips_theme(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            before = app.theme
            app.action_toggle_dark()
            await pilot.pause()
            assert app.theme != before
            app.action_toggle_dark()
            await pilot.pause()
            assert app.theme == before

    def test_refresh_interval_positive(self) -> None:
        from keeto.dashboard.tui.app import _REFRESH_INTERVAL

        assert _REFRESH_INTERVAL > 0

    @pytest.mark.asyncio
    async def test_compose_runs(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True):
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
        async with app.run_test(headless=True):
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
        from datetime import datetime

        dt = datetime.now(UTC) - timedelta(seconds=30)
        assert "s ago" in _age(dt)

    def test_age_minutes(self) -> None:
        from datetime import datetime

        dt = datetime.now(UTC) - timedelta(minutes=5)
        assert "m ago" in _age(dt)


class TestTimeline:
    def test_single_span_produces_one_line(self) -> None:
        from keeto.dashboard.tui.widgets.timeline import build_waterfall

        trace = _make_trace("t1", latency_ms=500.0)
        lines = build_waterfall(trace, bar_cols=40).splitlines()
        assert len(lines) == 1

    def test_bar_contains_block_char(self) -> None:
        from keeto.dashboard.tui.widgets.timeline import _BAR_CHAR, build_waterfall

        trace = _make_trace("t1", latency_ms=500.0)
        result = build_waterfall(trace, bar_cols=40)
        assert _BAR_CHAR in result

    def test_no_spans_returns_placeholder(self) -> None:
        from keeto.dashboard.tui.widgets.timeline import build_waterfall

        trace = Trace(trace_id="empty")
        result = build_waterfall(trace)
        assert "no spans" in result

    def test_multiple_spans_multiple_lines(self) -> None:
        from keeto.core.span import Span
        from keeto.dashboard.tui.widgets.timeline import build_waterfall

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


class TestPerformanceView:
    @pytest.mark.asyncio
    async def test_mounts(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True):
            assert app.query_one(PerformanceView) is not None

    @pytest.mark.asyncio
    async def test_refresh_data_populates_table(self, storage: MemoryStorage) -> None:
        traces = [
            _make_trace("t1", model="gpt-4o", provider="openai", latency_ms=300),
            _make_trace("t2", model="gpt-4o", provider="openai", latency_ms=600),
            _make_trace("t3", model="claude-3-5", provider="anthropic", latency_ms=800),
        ]
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            pv = app.query_one(PerformanceView)
            pv.refresh_data(traces)
            await pilot.pause()
            from textual.widgets import DataTable

            table = pv.query_one(DataTable)
            assert table.row_count == 2  # two distinct models


class TestPercentileHelper:
    def test_empty(self) -> None:
        from keeto.dashboard.tui.widgets.performance import _percentile

        assert _percentile([], 50) is None

    def test_single(self) -> None:
        from keeto.dashboard.tui.widgets.performance import _percentile

        assert _percentile([100.0], 50) == 100.0

    def test_p50(self) -> None:
        from keeto.dashboard.tui.widgets.performance import _percentile

        vals = [100.0, 200.0, 300.0, 400.0, 500.0]
        assert _percentile(vals, 50) == pytest.approx(300.0)

    def test_p95(self) -> None:
        from keeto.dashboard.tui.widgets.performance import _percentile

        vals = list(range(1, 101, 1))
        result = _percentile([float(v) for v in vals], 95)
        assert result is not None
        assert 94.0 <= result <= 96.0


class TestHistogram:
    def test_no_data_placeholder(self) -> None:
        from keeto.dashboard.tui.widgets.performance import _build_histogram

        assert _build_histogram([]) == "(no data)"

    def test_buckets_present(self) -> None:
        from keeto.dashboard.tui.widgets.performance import _build_histogram

        result = _build_histogram([50.0, 200.0, 700.0])
        # All bucket labels should be present (some with 0 count bars)
        assert "<100ms" in result
        assert "100-250ms" in result

    def test_bar_char_present(self) -> None:
        from keeto.dashboard.tui.widgets.performance import _HIST_BAR, _build_histogram

        result = _build_histogram([100.0, 100.0, 500.0])
        assert _HIST_BAR in result


class TestSearchFilter:
    @pytest.mark.asyncio
    async def test_filter_by_model(self, storage: MemoryStorage) -> None:
        from keeto.dashboard.tui.widgets.traces import TracesView

        traces = [
            _make_trace("t1", model="gpt-4o"),
            _make_trace("t2", model="claude-3-5"),
        ]
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            tv = app.query_one(TracesView)
            tv.refresh_data(traces)
            await pilot.pause()
            tv._filter = "claude"
            tv._apply_filter()
            await pilot.pause()
            assert tv.query_one(TraceListWidget).query_one("DataTable").row_count == 1

    @pytest.mark.asyncio
    async def test_filter_by_provider(self, storage: MemoryStorage) -> None:
        from keeto.dashboard.tui.widgets.traces import TracesView

        traces = [
            _make_trace("t1", provider="openai"),
            _make_trace("t2", provider="anthropic"),
            _make_trace("t3", provider="anthropic"),
        ]
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            tv = app.query_one(TracesView)
            tv.refresh_data(traces)
            await pilot.pause()
            tv._filter = "anthropic"
            tv._apply_filter()
            await pilot.pause()
            assert tv.query_one(TraceListWidget).query_one("DataTable").row_count == 2

    @pytest.mark.asyncio
    async def test_filter_error_keyword(self, storage: MemoryStorage) -> None:
        from keeto.dashboard.tui.widgets.traces import TracesView

        traces = [
            _make_trace("t1", error=False),
            _make_trace("t2", error=True),
        ]
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            tv = app.query_one(TracesView)
            tv.refresh_data(traces)
            await pilot.pause()
            tv._filter = "error"
            tv._apply_filter()
            await pilot.pause()
            assert tv.query_one(TraceListWidget).query_one("DataTable").row_count == 1

    @pytest.mark.asyncio
    async def test_empty_filter_shows_all(self, storage: MemoryStorage) -> None:
        from keeto.dashboard.tui.widgets.traces import TracesView

        traces = [_make_trace(f"t{i}") for i in range(5)]
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            tv = app.query_one(TracesView)
            tv.refresh_data(traces)
            await pilot.pause()
            tv._filter = ""
            tv._apply_filter()
            await pilot.pause()
            assert tv.query_one(TraceListWidget).query_one("DataTable").row_count == 5


class TestVimNavigation:
    @pytest.mark.asyncio
    async def test_j_moves_cursor_down(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        traces = [_make_trace(f"t{i}") for i in range(5)]
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update(traces)
            await pilot.pause()
            table = widget.query_one("DataTable")
            table.move_cursor(row=0)
            widget.action_cursor_down()
            await pilot.pause()
            assert table.cursor_row == 1

    @pytest.mark.asyncio
    async def test_k_moves_cursor_up(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        traces = [_make_trace(f"t{i}") for i in range(5)]
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update(traces)
            await pilot.pause()
            table = widget.query_one("DataTable")
            table.move_cursor(row=2)
            widget.action_cursor_up()
            await pilot.pause()
            assert table.cursor_row == 1

    @pytest.mark.asyncio
    async def test_g_jumps_to_top(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        traces = [_make_trace(f"t{i}") for i in range(5)]
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update(traces)
            await pilot.pause()
            table = widget.query_one("DataTable")
            table.move_cursor(row=4)
            widget.action_cursor_top()
            await pilot.pause()
            assert table.cursor_row == 0

    @pytest.mark.asyncio
    async def test_G_jumps_to_bottom(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        traces = [_make_trace(f"t{i}") for i in range(5)]
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update(traces)
            await pilot.pause()
            table = widget.query_one("DataTable")
            table.move_cursor(row=0)
            widget.action_cursor_bottom()
            await pilot.pause()
            assert table.cursor_row == 4

    @pytest.mark.asyncio
    async def test_j_clamps_at_bottom(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        traces = [_make_trace(f"t{i}") for i in range(3)]
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update(traces)
            await pilot.pause()
            table = widget.query_one("DataTable")
            table.move_cursor(row=2)  # last row
            widget.action_cursor_down()  # should not go past end
            await pilot.pause()
            assert table.cursor_row == 2

    @pytest.mark.asyncio
    async def test_k_clamps_at_top(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        traces = [_make_trace(f"t{i}") for i in range(3)]
        async with app.run_test(headless=True) as pilot:
            widget = app.query_one(TraceListWidget)
            widget.update(traces)
            await pilot.pause()
            table = widget.query_one("DataTable")
            table.move_cursor(row=0)
            widget.action_cursor_up()  # should not go below 0
            await pilot.pause()
            assert table.cursor_row == 0


class TestLiveRefresh:
    @pytest.mark.asyncio
    async def test_broadcast_updates_all_views(self, storage: MemoryStorage) -> None:
        """_broadcast_traces should reach TracesView, CostView, and PerformanceView."""
        traces = [
            _make_trace("t1", model="gpt-4o", cost_usd=0.001, latency_ms=300),
            _make_trace("t2", model="claude-3-5", provider="anthropic", cost_usd=0.002, latency_ms=600),
        ]
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            app._broadcast_traces(traces)
            await pilot.pause()
            # All three views should now show 2 distinct models
            from textual.widgets import DataTable

            cost_table = app.query_one(CostView).query_one(DataTable)
            perf_table = app.query_one(PerformanceView).query_one(DataTable)
            trace_table = app.query_one(TraceListWidget).query_one(DataTable)
            assert cost_table.row_count == 2
            assert perf_table.row_count == 2
            assert trace_table.row_count == 2


class TestCostView:
    @pytest.mark.asyncio
    async def test_cost_view_mounts(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True):
            from keeto.dashboard.tui.widgets.cost import CostView

            assert app.query_one(CostView) is not None

    @pytest.mark.asyncio
    async def test_refresh_data_populates_table(self, storage: MemoryStorage) -> None:
        from keeto.dashboard.tui.widgets.cost import CostView

        traces = [
            _make_trace("t1", model="gpt-4o", cost_usd=0.001),
            _make_trace("t2", model="gpt-4o", cost_usd=0.002),
            _make_trace("t3", model="claude-3-5-sonnet", provider="anthropic", cost_usd=0.003),
        ]
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            cv = app.query_one(CostView)
            cv.refresh_data(traces)
            await pilot.pause()
            table = cv.query_one("DataTable")
            # two distinct models
            assert table.row_count == 2

    def test_pct_helper(self) -> None:
        from keeto.dashboard.tui.widgets.cost import _pct

        assert _pct(1.0, 4.0) == "25.0%"
        assert _pct(0.0, 0.0) == "—"
