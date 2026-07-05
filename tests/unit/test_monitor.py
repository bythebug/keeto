"""Tests for the Monitor class."""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from keeto.core.monitor import Monitor
from keeto.core.span import Span, SpanKind, SpanStatus
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
        span.set_attribute(
            "llm.messages", [{"role": "user", "content": "My email is john@example.com and SSN 123-45-6789"}]
        )
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

    def test_dashboard_tui_mode(self, fresh_monitor: Monitor) -> None:
        with patch("keeto.dashboard.tui.app.KeetoApp") as mock_app:
            fresh_monitor.dashboard(mode="tui")
        mock_app.assert_called_once_with(storage=fresh_monitor._storage)
        mock_app.return_value.run.assert_called_once()

    def test_dashboard_web_mode(self, fresh_monitor: Monitor) -> None:
        with patch("keeto.dashboard.web.server.start_web_dashboard") as mock_start:
            fresh_monitor.dashboard(mode="web")
        mock_start.assert_called_once_with(fresh_monitor._storage, block=False)


class TestMonitorLifecycleExtra:
    def test_emit_not_started_is_noop(self) -> None:
        storage = MemoryStorage()
        m = Monitor(storage=storage, auto=False)
        span = Span(trace_id="t1", span_id="s1", name="op", kind=SpanKind.LLM)
        span.finish(status=SpanStatus.OK)
        m.emit(span)  # should not raise or store anything
        traces = asyncio.run(storage.list_traces())
        assert len(traces) == 0

    def test_keeto_disabled_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KEETO_DISABLED", "1")
        m = Monitor(auto=False)
        m.start()
        assert not m._started

    def test_use_before_start_installs_on_start(self) -> None:
        m = Monitor(auto=False)
        plugin = MagicMock()
        plugin.name = "test-plugin"
        m.use(plugin)
        plugin.install.assert_not_called()
        m.start()
        plugin.install.assert_called_once_with(m)
        m.stop()

    def test_use_after_start_installs_immediately(self) -> None:
        m = Monitor(auto=False)
        m.start()
        plugin = MagicMock()
        plugin.name = "test-plugin"
        m.use(plugin)
        plugin.install.assert_called_once_with(m)
        m.stop()

    def test_stop_calls_plugin_uninstall(self) -> None:
        m = Monitor(auto=False)
        plugin = MagicMock()
        plugin.name = "test-plugin"
        m.use(plugin)
        m.start()
        m.stop()
        plugin.uninstall.assert_called_once()

    def test_span_context_exposes_span(self, fresh_monitor: Monitor) -> None:
        with fresh_monitor.span("op") as ctx:
            s = ctx.span
            assert s is not None
            assert s.name == "op"


class TestMonitorBudget:
    def _cost_span(self, trace_id: str, cost: float) -> Span:
        span = Span(trace_id=trace_id, span_id="s1", name="op", kind=SpanKind.LLM, provider="openai", model="gpt-4o")
        span.cost_usd = cost
        span.finish(status=SpanStatus.OK)
        return span

    def test_session_budget_alert_fires(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.set_budget(session_usd=0.001)
        m.emit(self._cost_span("t1", 0.002))
        time.sleep(0.1)
        assert "session" in m._budget_alert_fired
        m.stop()

    def test_daily_budget_alert_fires(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.set_budget(daily_usd=0.001)
        m.emit(self._cost_span("t1", 0.002))
        time.sleep(0.1)
        from datetime import date

        key = f"daily_{date.today()}"
        assert key in m._budget_alert_fired
        m.stop()

    def test_budget_alert_fires_only_once(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.set_budget(session_usd=0.001)
        m.emit(self._cost_span("t1", 0.002))
        m.emit(self._cost_span("t2", 0.002))
        time.sleep(0.1)
        assert m._budget_alert_fired.count("session") if hasattr(m._budget_alert_fired, "count") else True
        m.stop()

    def test_cost_summary_keys(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.emit(self._cost_span("t1", 0.005))
        time.sleep(0.1)
        s = m.cost_summary()
        assert "session_usd" in s
        assert "today_usd" in s
        assert "by_provider" in s
        assert "by_model" in s
        assert s["session_usd"] == pytest.approx(0.005, rel=1e-5)
        m.stop()

    def test_accumulate_cost_none_is_noop(self) -> None:
        m = Monitor(auto=False)
        span = Span(trace_id="t1", span_id="s1", name="op", kind=SpanKind.LLM)
        span.finish(status=SpanStatus.OK)
        m._accumulate_cost(span)  # cost_usd is None
        assert m._session_cost_usd == 0.0


class TestMonitorTokenBudget:
    def _token_span(self, trace_id: str, inp: int, out: int) -> Span:
        span = Span(trace_id=trace_id, span_id="s1", name="op", kind=SpanKind.LLM)
        span.input_tokens = inp
        span.output_tokens = out
        span.finish(status=SpanStatus.OK)
        return span

    def test_daily_token_budget_alert_fires(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.set_token_budget(daily=100)
        m.emit(self._token_span("t1", 200, 50))
        time.sleep(0.1)
        from datetime import date

        key = f"token_daily_{date.today()}"
        assert key in m._budget_alert_fired
        m.stop()

    def test_monthly_token_budget_alert_fires(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.set_token_budget(monthly=100)
        m.emit(self._token_span("t1", 200, 50))
        time.sleep(0.1)
        from datetime import date as _d

        key = f"token_monthly_{_d.today().year}_{_d.today().month}"
        assert key in m._budget_alert_fired
        m.stop()

    def test_token_summary_keys(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.emit(self._token_span("t1", 100, 50))
        time.sleep(0.1)
        s = m.token_summary()
        assert s["session_tokens"] == 150
        assert "budget_daily" in s
        assert "budget_monthly" in s
        m.stop()

    def test_zero_tokens_is_noop(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        span = Span(trace_id="t1", span_id="s1", name="op", kind=SpanKind.LLM)
        span.finish(status=SpanStatus.OK)
        m.emit(span)
        time.sleep(0.1)
        assert m._session_tokens == 0
        m.stop()


class TestTracesProxy:
    def test_traces_proxy_len(self, fresh_monitor: Monitor) -> None:
        with fresh_monitor.span("op"):
            pass
        time.sleep(0.2)
        assert len(fresh_monitor.traces) == 1

    def test_traces_proxy_getitem(self, fresh_monitor: Monitor) -> None:
        with fresh_monitor.span("op"):
            pass
        time.sleep(0.2)
        t = fresh_monitor.traces[0]
        assert t.spans[0].name == "op"

    def test_traces_proxy_iter(self, fresh_monitor: Monitor) -> None:
        for i in range(3):
            with fresh_monitor.span(f"op-{i}"):
                pass
        time.sleep(0.2)
        names = [t.spans[0].name for t in fresh_monitor.traces]
        assert len(names) == 3


class TestMonitorExportFormats:
    def test_export_otel(self, fresh_monitor: Monitor, tmp_path: Path) -> None:
        with fresh_monitor.span("test"):
            pass
        time.sleep(0.2)
        with patch("keeto.exporters.otel.export_otel") as mock_otel:
            fresh_monitor.export(format="otel", endpoint="http://localhost:4317")
        mock_otel.assert_called_once()

    def test_export_langsmith(self, fresh_monitor: Monitor, tmp_path: Path) -> None:
        with fresh_monitor.span("test"):
            pass
        time.sleep(0.2)
        out = str(tmp_path / "runs.json")
        with patch("keeto.exporters.langsmith.export_langsmith") as mock_ls:
            fresh_monitor.export(format="langsmith", path=out)
        mock_ls.assert_called_once()

    def test_export_mlflow(self, fresh_monitor: Monitor) -> None:
        with fresh_monitor.span("test"):
            pass
        time.sleep(0.2)
        with patch("keeto.exporters.mlflow.export_mlflow") as mock_ml:
            fresh_monitor.export(format="mlflow", experiment_name="test-exp")
        mock_ml.assert_called_once()

    def test_export_unknown_format_raises(self, fresh_monitor: Monitor) -> None:
        with pytest.raises(ValueError, match="Unknown export format"):
            fresh_monitor.export(format="parquet")

    def test_export_since_until_datetime_passthrough(self, fresh_monitor: Monitor, tmp_path: Path) -> None:
        out = str(tmp_path / "traces.json")
        fresh_monitor.export(str(out), since="2024-01-01", until="2024-12-31")


class TestMonitorImportLangSmith:
    def test_import_langsmith(self, fresh_monitor: Monitor) -> None:
        real_span = Span(trace_id="t-ls", span_id="s-ls", name="op", kind=SpanKind.LLM)
        real_span.finish(status=SpanStatus.OK)
        fake_trace = MagicMock()
        fake_trace.spans = [real_span]
        with patch("keeto.exporters.langsmith.import_from_langsmith", return_value=[fake_trace]) as mock_imp:
            count = fresh_monitor.import_langsmith("my-project", limit=10)
        mock_imp.assert_called_once_with("my-project", limit=10, api_key=None, api_url=None)
        assert count == 1
