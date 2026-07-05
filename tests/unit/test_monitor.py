"""Tests for the Monitor class."""

import asyncio
import json
import time
from pathlib import Path

import pytest
from keeto.core.monitor import Monitor
from keeto.core.span import SpanKind, SpanStatus
from keeto.storage.memory import MemoryStorage


@pytest.fixture
def fresh_monitor(tmp_path: Path) -> Monitor:
    m = Monitor(storage=MemoryStorage(), auto=False)
    m.start()
    yield m
    m.stop()


class TestMonitorLifecycle:
    def test_start_stop(self) -> None:
        m = Monitor(auto=False)
        m.start()
        assert m._started
        m.stop()
        assert not m._started

    def test_context_manager(self) -> None:
        m = Monitor(auto=False)
        with m:
            assert m._started
        assert not m._started

    def test_double_start_idempotent(self) -> None:
        m = Monitor(auto=False)
        m.start()
        m.start()  # should not raise
        m.stop()


class TestMonitorSpan:
    def test_span_context_manager(self, fresh_monitor: Monitor) -> None:
        with fresh_monitor.span("my-op") as ctx:
            ctx.set_attribute("key", "value")

        time.sleep(0.2)
        traces = asyncio.run(fresh_monitor._storage.list_traces())
        assert len(traces) == 1
        span = traces[0].spans[0]
        assert span.name == "my-op"
        assert span.attributes["key"] == "value"
        assert span.status == SpanStatus.OK

    def test_span_records_error(self, fresh_monitor: Monitor) -> None:
        with pytest.raises(ValueError):
            with fresh_monitor.span("failing-op"):
                raise ValueError("test error")

        time.sleep(0.2)
        traces = asyncio.run(fresh_monitor._storage.list_traces())
        assert len(traces) == 1
        assert traces[0].spans[0].status == SpanStatus.ERROR

    def test_span_custom_kind(self, fresh_monitor: Monitor) -> None:
        with fresh_monitor.span("embed", kind=SpanKind.EMBEDDING):
            pass
        time.sleep(0.2)
        traces = asyncio.run(fresh_monitor._storage.list_traces())
        assert traces[0].spans[0].kind == SpanKind.EMBEDDING


class TestMonitorExport:
    def test_export_json(self, fresh_monitor: Monitor, tmp_path: Path) -> None:
        with fresh_monitor.span("test"):
            pass
        time.sleep(0.2)

        out = tmp_path / "traces.json"
        fresh_monitor.export(str(out))
        data = json.loads(out.read_text())
        assert isinstance(data, list)
        assert len(data) == 1

    def test_export_csv(self, fresh_monitor: Monitor, tmp_path: Path) -> None:
        with fresh_monitor.span("test"):
            pass
        time.sleep(0.2)

        out = tmp_path / "traces.csv"
        fresh_monitor.export(str(out))
        content = out.read_text()
        assert "trace_id" in content
        assert "latency_ms" in content


class TestMonitorDashboard:
    def test_dashboard_rich_no_traces(self, capsys: pytest.CaptureFixture) -> None:
        m = Monitor(auto=False)
        m.start()
        m.dashboard(mode="rich")
        m.stop()
        # Should not raise; no output expected to stdout

    def test_dashboard_unknown_mode(self, fresh_monitor: Monitor) -> None:
        with pytest.raises(ValueError, match="Unknown dashboard mode"):
            fresh_monitor.dashboard(mode="invalid")
