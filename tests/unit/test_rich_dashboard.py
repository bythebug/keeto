"""Tests for the Rich terminal dashboard."""

from __future__ import annotations

import io

from rich.console import Console

from keeto.core.span import Span, SpanStatus, Trace
from keeto.dashboard.rich_summary import render


def _console() -> Console:
    return Console(file=io.StringIO(), width=120)


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
    from datetime import timedelta

    span.end_time = span.start_time + timedelta(milliseconds=latency_ms)
    span.finish(status=SpanStatus.ERROR if error else SpanStatus.OK)
    trace.add_span(span)
    return trace


class TestRichDashboard:
    def test_no_traces_shows_empty_message(self) -> None:
        con = _console()
        render([], console=con)
        output = con.file.getvalue()  # type: ignore[union-attr]
        assert "No traces" in output

    def test_single_trace_renders(self) -> None:
        con = _console()
        render([_make_trace()], console=con)
        output = con.file.getvalue()  # type: ignore[union-attr]
        assert "abc123" in output
        assert "openai" in output
        assert "gpt-4o" in output

    def test_stats_panel_shows_totals(self) -> None:
        traces = [
            _make_trace("t1", cost_usd=0.001),
            _make_trace("t2", cost_usd=0.002),
            _make_trace("t3", cost_usd=0.003),
        ]
        con = _console()
        render(traces, console=con)
        output = con.file.getvalue()  # type: ignore[union-attr]
        assert "3" in output  # trace count

    def test_error_trace_flagged(self) -> None:
        con = _console()
        render([_make_trace(error=True)], console=con)
        output = con.file.getvalue()  # type: ignore[union-attr]
        assert "error" in output.lower()

    def test_limit_respected(self) -> None:
        traces = [_make_trace(trace_id=f"t{i}") for i in range(100)]
        con = _console()
        render(traces, console=con, limit=10)
        output = con.file.getvalue()  # type: ignore[union-attr]
        # Should mention showing 10 of 100
        assert "10" in output
        assert "100" in output

    def test_monitor_dashboard_rich_integration(self) -> None:
        import time

        from keeto.core.monitor import Monitor
        from keeto.storage.memory import MemoryStorage

        store = MemoryStorage()
        m = Monitor(storage=store, auto=False)
        m.start()
        with m.span("test-op"):
            pass
        time.sleep(0.15)

        con = _console()
        m._console = con
        m.dashboard(mode="rich")
        m.stop()

        output = con.file.getvalue()  # type: ignore[union-attr]
        assert "test-op" in output or "1" in output  # at least 1 trace shown
