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
        with pytest.raises(ValueError), fresh_monitor.span("failing-op"):
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


class TestMonitorSampling:
    def test_sample_rate_zero_drops_all_ok_spans(self) -> None:
        storage = MemoryStorage()
        m = Monitor(storage=storage, auto=False, sample_rate=0.0)
        m.start()
        from keeto.core.span import Span, SpanKind, SpanStatus

        span = Span(trace_id="t1", span_id="s1", name="openai.chat", kind=SpanKind.LLM)
        span.finish(status=SpanStatus.OK)
        m.emit(span)
        time.sleep(0.2)
        traces = asyncio.run(storage.list_traces())
        assert len(traces) == 0
        m.stop()

    def test_sample_rate_zero_always_captures_errors(self) -> None:
        storage = MemoryStorage()
        m = Monitor(storage=storage, auto=False, sample_rate=0.0)
        m.start()
        from keeto.core.span import Span, SpanKind, SpanStatus

        span = Span(trace_id="t2", span_id="s2", name="openai.chat", kind=SpanKind.LLM)
        span.finish(status=SpanStatus.ERROR)
        m.emit(span)
        time.sleep(0.2)
        traces = asyncio.run(storage.list_traces())
        assert len(traces) == 1
        m.stop()

    def test_sample_rate_one_captures_all(self) -> None:
        storage = MemoryStorage()
        m = Monitor(storage=storage, auto=False, sample_rate=1.0)
        m.start()
        from keeto.core.span import Span, SpanKind, SpanStatus

        for i in range(5):
            span = Span(trace_id=f"t{i}", span_id=f"s{i}", name="op", kind=SpanKind.LLM)
            span.finish(status=SpanStatus.OK)
            m.emit(span)
        time.sleep(0.2)
        traces = asyncio.run(storage.list_traces(limit=10))
        assert len(traces) == 5
        m.stop()


class TestMonitorPiiScrubbing:
    def _make_span(self, trace_id: str = "t1"):  # type: ignore[return]
        from keeto.core.span import Span, SpanKind, SpanStatus
        span = Span(trace_id=trace_id, span_id="s1", name="op", kind=SpanKind.LLM)
        span.set_attribute("llm.messages", [
            {"role": "user", "content": "My email is john@example.com and SSN 123-45-6789"}
        ])
        span.set_attribute("llm.system_prompt", "Call me at (555) 867-5309")
        span.finish(status=SpanStatus.OK)
        return span

    def test_scrub_pii_redacts_email_and_ssn(self) -> None:
        storage = MemoryStorage()
        m = Monitor(storage=storage, auto=False, scrub_pii=True)
        m.start()
        m.emit(self._make_span())
        time.sleep(0.2)
        traces = asyncio.run(storage.list_traces())
        span = traces[0].spans[0]
        msgs = span.attributes["llm.messages"]
        assert "[EMAIL]" in msgs[0]["content"]
        assert "[SSN]" in msgs[0]["content"]
        assert "john@example.com" not in msgs[0]["content"]
        m.stop()

    def test_scrub_pii_redacts_phone(self) -> None:
        storage = MemoryStorage()
        m = Monitor(storage=storage, auto=False, scrub_pii=True)
        m.start()
        m.emit(self._make_span())
        time.sleep(0.2)
        traces = asyncio.run(storage.list_traces())
        span = traces[0].spans[0]
        assert "[PHONE]" in span.attributes["llm.system_prompt"]
        assert "867-5309" not in span.attributes["llm.system_prompt"]
        m.stop()

    def test_scrub_pii_false_leaves_data_intact(self) -> None:
        storage = MemoryStorage()
        m = Monitor(storage=storage, auto=False, scrub_pii=False)
        m.start()
        m.emit(self._make_span())
        time.sleep(0.2)
        traces = asyncio.run(storage.list_traces())
        span = traces[0].spans[0]
        assert "john@example.com" in span.attributes["llm.messages"][0]["content"]
        m.stop()

    def test_custom_pii_patterns(self) -> None:
        storage = MemoryStorage()
        m = Monitor(storage=storage, auto=False, scrub_pii=True, pii_patterns=[r"\bACCT-\d{8}\b"])
        m.start()
        from keeto.core.span import Span, SpanKind, SpanStatus
        span = Span(trace_id="t1", span_id="s1", name="op", kind=SpanKind.LLM)
        span.set_attribute("note", "Account ACCT-12345678 was referenced")
        span.finish(status=SpanStatus.OK)
        m.emit(span)
        time.sleep(0.2)
        traces = asyncio.run(storage.list_traces())
        assert "[REDACTED]" in traces[0].spans[0].attributes["note"]
        assert "ACCT-12345678" not in traces[0].spans[0].attributes["note"]
        m.stop()


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
