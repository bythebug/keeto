"""Tests for the Milestone 4 analysis engine (issues #66–#80)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from keeto._pricing import CONTEXT_WINDOWS, context_window
from keeto.analyzers.comparison import TraceComparison
from keeto.analyzers.cost import (
    aggregate_cost_by_model,
    aggregate_cost_by_provider,
    detect_cost_anomalies,
)
from keeto.analyzers.errors import cluster_errors
from keeto.analyzers.performance import detect_latency_anomalies, latency_percentiles
from keeto.analyzers.recommendations import (
    CacheCandidatesRule,
    ContextWasteRule,
    CostAnomalyRule,
    ErrorPatternRule,
    HallucinationHeuristicRule,
    LatencyAnomalyRule,
    ModelSwitchRule,
    PromptSizeRule,
    RecommendationsEngine,
    RetryLoopRule,
)
from keeto.core.monitor import Monitor
from keeto.core.span import Span, SpanKind, SpanStatus, Trace
from keeto.storage.memory import MemoryStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_span(
    trace_id: str = "trace-1",
    span_id: str = "span-1",
    provider: str | None = "openai",
    model: str | None = "gpt-4o",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    cost_usd: float | None = None,
    latency_ms: float | None = 500.0,
    status: SpanStatus = SpanStatus.OK,
    status_message: str | None = None,
    kind: SpanKind = SpanKind.LLM,
    **attrs: object,
) -> Span:
    now = datetime.now(UTC)
    span = Span(
        trace_id=trace_id,
        span_id=span_id,
        name=f"{provider}.chat",
        kind=kind,
        start_time=now,
        end_time=now,
        status=status,
        status_message=status_message,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        cost_usd=cost_usd,
    )
    for k, v in attrs.items():
        span.set_attribute(k, v)
    if latency_ms is not None:
        from datetime import timedelta

        span.end_time = span.start_time + timedelta(milliseconds=latency_ms)
    return span


def _make_trace(*spans: Span, trace_id: str = "trace-1") -> Trace:
    trace = Trace(trace_id=trace_id)
    for s in spans:
        trace.add_span(s)
    return trace


# ---------------------------------------------------------------------------
# _pricing.py additions
# ---------------------------------------------------------------------------


class TestPricingAdditions:
    def test_context_windows_dict_populated(self) -> None:
        assert "gpt-4o" in CONTEXT_WINDOWS
        assert CONTEXT_WINDOWS["gpt-4o"] == 128_000
        assert "claude-sonnet-4-6" in CONTEXT_WINDOWS

    def test_context_window_exact_match(self) -> None:
        assert context_window("gpt-4o") == 128_000

    def test_context_window_date_suffix_stripped(self) -> None:
        # e.g. gpt-4o-2024-11-20 → gpt-4o
        result = context_window("gpt-4o-2024-11-20")
        assert result == 128_000

    def test_context_window_unknown_returns_none(self) -> None:
        assert context_window("unknown-model-xyz") is None


# ---------------------------------------------------------------------------
# Rule #67: PromptSizeRule
# ---------------------------------------------------------------------------


class TestPromptSizeRule:
    def test_flags_large_prompt(self) -> None:
        span = _make_span(model="gpt-4o", input_tokens=100_000)  # 78% of 128k
        trace = _make_trace(span)
        recs = PromptSizeRule().check([trace])
        assert len(recs) == 1
        assert recs[0].rule == "prompt_size"

    def test_ignores_small_prompt(self) -> None:
        span = _make_span(model="gpt-4o", input_tokens=10_000)  # 7.8%
        trace = _make_trace(span)
        recs = PromptSizeRule().check([trace])
        assert recs == []

    def test_ignores_unknown_model(self) -> None:
        span = _make_span(model="unknown-model", input_tokens=999_999)
        trace = _make_trace(span)
        recs = PromptSizeRule().check([trace])
        assert recs == []


# ---------------------------------------------------------------------------
# Rule #68: CacheCandidatesRule
# ---------------------------------------------------------------------------


class TestCacheCandidatesRule:
    def test_flags_repeated_uncached_call(self) -> None:
        span1 = _make_span(trace_id="t1", span_id="s1", model="gpt-4o", **{"llm.message_count": 5})
        span2 = _make_span(trace_id="t2", span_id="s2", model="gpt-4o", **{"llm.message_count": 5})
        traces = [_make_trace(span1, trace_id="t1"), _make_trace(span2, trace_id="t2")]
        recs = CacheCandidatesRule().check(traces)
        assert len(recs) == 1
        assert recs[0].rule == "cache_candidate"

    def test_no_flag_when_cached(self) -> None:
        span1 = _make_span(trace_id="t1", span_id="s1", model="gpt-4o", cached_tokens=100, **{"llm.message_count": 5})
        span2 = _make_span(trace_id="t2", span_id="s2", model="gpt-4o", **{"llm.message_count": 5})
        traces = [_make_trace(span1, trace_id="t1"), _make_trace(span2, trace_id="t2")]
        recs = CacheCandidatesRule().check(traces)
        assert recs == []

    def test_no_flag_single_call(self) -> None:
        span = _make_span(model="gpt-4o", **{"llm.message_count": 5})
        recs = CacheCandidatesRule().check([_make_trace(span)])
        assert recs == []


# ---------------------------------------------------------------------------
# Rule #69: ModelSwitchRule
# ---------------------------------------------------------------------------


class TestModelSwitchRule:
    def test_suggests_cheaper_model(self) -> None:
        span = _make_span(model="gpt-4o", provider="openai")
        trace = _make_trace(span)
        recs = ModelSwitchRule().check([trace])
        assert len(recs) == 1
        assert "gpt-4o-mini" in recs[0].message

    def test_no_suggestion_for_cheap_model(self) -> None:
        span = _make_span(model="gpt-4o-mini", provider="openai")
        recs = ModelSwitchRule().check([_make_trace(span)])
        # gpt-4o-mini has no cheaper alternative defined
        assert recs == []

    def test_deduplicates_same_model(self) -> None:
        span1 = _make_span(trace_id="t1", span_id="s1", model="gpt-4o")
        span2 = _make_span(trace_id="t2", span_id="s2", model="gpt-4o")
        traces = [_make_trace(span1, trace_id="t1"), _make_trace(span2, trace_id="t2")]
        recs = ModelSwitchRule().check(traces)
        assert len(recs) == 1  # deduplicated


# ---------------------------------------------------------------------------
# Rule #70: ContextWasteRule
# ---------------------------------------------------------------------------


class TestContextWasteRule:
    def test_flags_repeated_large_system_prompt(self) -> None:
        sys_prompt = "You are a helpful assistant. " * 100  # large

        def _span_with_sys(trace_id: str, span_id: str) -> Span:
            s = _make_span(trace_id=trace_id, span_id=span_id, model="gpt-4o", input_tokens=500)
            s.set_attribute("llm.system_prompt", sys_prompt)
            return s

        traces = [
            _make_trace(_span_with_sys("t1", "s1"), trace_id="t1"),
            _make_trace(_span_with_sys("t2", "s2"), trace_id="t2"),
            _make_trace(_span_with_sys("t3", "s3"), trace_id="t3"),
        ]
        recs = ContextWasteRule().check(traces)
        assert len(recs) == 1
        assert recs[0].rule == "context_waste"

    def test_no_flag_below_threshold(self) -> None:
        # Only 2 calls (need MIN_CALLS=3)
        sys_prompt = "System. " * 100
        span1 = _make_span(trace_id="t1", span_id="s1", model="gpt-4o", input_tokens=500)
        span1.set_attribute("llm.system_prompt", sys_prompt)
        span2 = _make_span(trace_id="t2", span_id="s2", model="gpt-4o", input_tokens=500)
        span2.set_attribute("llm.system_prompt", sys_prompt)
        traces = [_make_trace(span1, trace_id="t1"), _make_trace(span2, trace_id="t2")]
        recs = ContextWasteRule().check(traces)
        assert recs == []


# ---------------------------------------------------------------------------
# Rule #71: RetryLoopRule
# ---------------------------------------------------------------------------


class TestRetryLoopRule:
    def test_flags_high_retry_count(self) -> None:
        span = _make_span(**{"llm.retry_count": 5})
        recs = RetryLoopRule().check([_make_trace(span)])
        assert len(recs) == 1
        assert recs[0].rule == "retry_loop"

    def test_no_flag_low_retry_count(self) -> None:
        span = _make_span(**{"llm.retry_count": 2})
        recs = RetryLoopRule().check([_make_trace(span)])
        assert recs == []

    def test_no_flag_zero_retries(self) -> None:
        span = _make_span()
        recs = RetryLoopRule().check([_make_trace(span)])
        assert recs == []


# ---------------------------------------------------------------------------
# Rule #72: HallucinationHeuristicRule
# ---------------------------------------------------------------------------


class TestHallucinationHeuristicRule:
    def test_flags_truncated_response(self) -> None:
        span = _make_span(**{"llm.finish_reason": "length"})
        recs = HallucinationHeuristicRule().check([_make_trace(span)])
        assert len(recs) == 1
        assert "length" in recs[0].message

    def test_flags_high_output_ratio(self) -> None:
        span = _make_span(input_tokens=100, output_tokens=600)
        recs = HallucinationHeuristicRule().check([_make_trace(span)])
        assert len(recs) == 1
        assert "ratio" in recs[0].message.lower()

    def test_no_flag_normal_response(self) -> None:
        span = _make_span(input_tokens=500, output_tokens=200, **{"llm.finish_reason": "stop"})
        recs = HallucinationHeuristicRule().check([_make_trace(span)])
        assert recs == []


# ---------------------------------------------------------------------------
# Rule #73: CostAnomalyRule
# ---------------------------------------------------------------------------


class TestCostAnomalyRule:
    def test_flags_cost_outlier(self) -> None:
        # 5 normal spans + 1 outlier
        traces = [
            _make_trace(_make_span(trace_id=f"t{i}", span_id=f"s{i}", cost_usd=0.001), trace_id=f"t{i}")
            for i in range(5)
        ]
        traces.append(
            _make_trace(
                _make_span(trace_id="t-outlier", span_id="s-outlier", cost_usd=1.0),
                trace_id="t-outlier",
            )
        )
        recs = CostAnomalyRule().check(traces)
        assert len(recs) >= 1
        assert recs[0].rule == "cost_anomaly"

    def test_no_flag_uniform_costs(self) -> None:
        traces = [
            _make_trace(_make_span(trace_id=f"t{i}", span_id=f"s{i}", cost_usd=0.001), trace_id=f"t{i}")
            for i in range(10)
        ]
        recs = CostAnomalyRule().check(traces)
        assert recs == []

    def test_no_flag_too_few_spans(self) -> None:
        traces = [
            _make_trace(_make_span(trace_id="t1", cost_usd=0.001), trace_id="t1"),
            _make_trace(_make_span(trace_id="t2", cost_usd=100.0), trace_id="t2"),
        ]
        recs = CostAnomalyRule().check(traces)
        assert recs == []  # need at least 3 spans


# ---------------------------------------------------------------------------
# Rule #74: LatencyAnomalyRule
# ---------------------------------------------------------------------------


class TestLatencyAnomalyRule:
    def test_flags_latency_outlier(self) -> None:
        traces = [
            _make_trace(_make_span(trace_id=f"t{i}", span_id=f"s{i}", latency_ms=200), trace_id=f"t{i}")
            for i in range(5)
        ]
        traces.append(
            _make_trace(
                _make_span(trace_id="t-slow", span_id="s-slow", latency_ms=5000),
                trace_id="t-slow",
            )
        )
        recs = LatencyAnomalyRule().check(traces)
        assert len(recs) >= 1
        assert recs[0].rule == "latency_anomaly"

    def test_no_flag_uniform_latency(self) -> None:
        traces = [
            _make_trace(_make_span(trace_id=f"t{i}", span_id=f"s{i}", latency_ms=300), trace_id=f"t{i}")
            for i in range(8)
        ]
        recs = LatencyAnomalyRule().check(traces)
        assert recs == []


# ---------------------------------------------------------------------------
# Rule #75: ErrorPatternRule
# ---------------------------------------------------------------------------


class TestErrorPatternRule:
    def test_flags_repeated_error(self) -> None:
        def _err_span(tid: str, sid: str) -> Span:
            return _make_span(
                trace_id=tid,
                span_id=sid,
                status=SpanStatus.ERROR,
                status_message="RateLimitError: Too many requests",
            )

        traces = [
            _make_trace(_err_span("t1", "s1"), trace_id="t1"),
            _make_trace(_err_span("t2", "s2"), trace_id="t2"),
        ]
        recs = ErrorPatternRule().check(traces)
        assert len(recs) == 1
        assert "RateLimitError" in recs[0].message

    def test_no_flag_single_error(self) -> None:
        span = _make_span(status=SpanStatus.ERROR, status_message="SomeError: oops")
        recs = ErrorPatternRule().check([_make_trace(span)])
        assert recs == []


# ---------------------------------------------------------------------------
# RecommendationsEngine integration
# ---------------------------------------------------------------------------


class TestRecommendationsEngine:
    def test_returns_report_no_traces(self) -> None:
        engine = RecommendationsEngine()
        report = engine.analyze([])
        assert report.recommendations == []
        assert "no recommendations" in str(report)

    def test_rule_failure_does_not_crash(self) -> None:
        from keeto.analyzers.recommendations import Rule, RuleRegistry

        class BrokenRule(Rule):
            name = "broken"
            severity = "info"

            def check(self, traces: list) -> list:
                raise RuntimeError("boom")

        registry = RuleRegistry()
        registry.register(BrokenRule())
        engine = RecommendationsEngine(registry)
        report = engine.analyze([_make_trace(_make_span())])
        assert report.recommendations == []  # failure swallowed

    def test_str_output_sorted_by_severity(self) -> None:
        from keeto.analyzers.recommendations import Recommendation, RecommendationsReport

        report = RecommendationsReport(
            recommendations=[
                Recommendation(severity="info", rule="r1", message="info_msg"),
                Recommendation(severity="error", rule="r2", message="error_msg"),
                Recommendation(severity="warning", rule="r3", message="warn_msg"),
            ]
        )
        output = str(report)
        error_pos = output.index("error_msg")
        warn_pos = output.index("warn_msg")
        info_pos = output.index("info_msg")
        assert error_pos < warn_pos < info_pos


# ---------------------------------------------------------------------------
# cost.py utilities
# ---------------------------------------------------------------------------


class TestCostUtilities:
    def test_detect_cost_anomalies(self) -> None:
        traces = [
            _make_trace(_make_span(trace_id=f"t{i}", span_id=f"s{i}", cost_usd=0.001), trace_id=f"t{i}")
            for i in range(5)
        ]
        traces.append(
            _make_trace(
                _make_span(trace_id="tx", span_id="sx", cost_usd=5.0),
                trace_id="tx",
            )
        )
        anomalies = detect_cost_anomalies(traces)
        assert len(anomalies) >= 1
        assert anomalies[0].z_score > 2.0

    def test_aggregate_cost_by_model(self) -> None:
        traces = [
            _make_trace(_make_span(model="gpt-4o", cost_usd=0.10)),
            _make_trace(_make_span(trace_id="t2", span_id="s2", model="gpt-4o-mini", cost_usd=0.01)),
        ]
        result = aggregate_cost_by_model(traces)
        assert result["gpt-4o"] == pytest.approx(0.10)
        assert result["gpt-4o-mini"] == pytest.approx(0.01)

    def test_aggregate_cost_by_provider(self) -> None:
        traces = [
            _make_trace(_make_span(provider="openai", cost_usd=0.10)),
            _make_trace(_make_span(trace_id="t2", span_id="s2", provider="anthropic", cost_usd=0.05)),
        ]
        result = aggregate_cost_by_provider(traces)
        assert "openai" in result
        assert "anthropic" in result


# ---------------------------------------------------------------------------
# performance.py utilities
# ---------------------------------------------------------------------------


class TestPerformanceUtilities:
    def test_latency_percentiles(self) -> None:
        latencies = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        traces = [
            _make_trace(_make_span(trace_id=f"t{i}", span_id=f"s{i}", latency_ms=lat), trace_id=f"t{i}")
            for i, lat in enumerate(latencies)
        ]
        pcts = latency_percentiles(traces)
        assert "p50" in pcts
        assert "p95" in pcts
        assert pcts["min"] == 100
        assert pcts["max"] == 1000

    def test_detect_latency_anomalies(self) -> None:
        traces = [
            _make_trace(_make_span(trace_id=f"t{i}", span_id=f"s{i}", latency_ms=300), trace_id=f"t{i}")
            for i in range(5)
        ]
        traces.append(
            _make_trace(
                _make_span(trace_id="tx", span_id="sx", latency_ms=10_000),
                trace_id="tx",
            )
        )
        anomalies = detect_latency_anomalies(traces)
        assert len(anomalies) >= 1


# ---------------------------------------------------------------------------
# errors.py utilities
# ---------------------------------------------------------------------------


class TestErrorUtilities:
    def test_cluster_errors_by_type(self) -> None:
        def _err(tid: str, sid: str, msg: str) -> Span:
            return _make_span(trace_id=tid, span_id=sid, status=SpanStatus.ERROR, status_message=msg)

        traces = [
            _make_trace(_err("t1", "s1", "RateLimitError: 429"), trace_id="t1"),
            _make_trace(_err("t2", "s2", "RateLimitError: quota exceeded"), trace_id="t2"),
            _make_trace(_err("t3", "s3", "AuthError: invalid key"), trace_id="t3"),
        ]
        clusters = cluster_errors(traces)
        patterns = [c.pattern for c in clusters]
        assert any("RateLimitError" in p for p in patterns)
        rate_cluster = next(c for c in clusters if "RateLimitError" in c.pattern)
        assert rate_cluster.count == 2

    def test_no_errors_returns_empty(self) -> None:
        trace = _make_trace(_make_span())
        assert cluster_errors([trace]) == []


# ---------------------------------------------------------------------------
# TraceComparison (#79)
# ---------------------------------------------------------------------------


class TestTraceComparison:
    def _trace_with_costs(
        self,
        trace_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: float,
    ) -> Trace:
        span = _make_span(
            trace_id=trace_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
        return _make_trace(span, trace_id=trace_id)

    def test_comparison_fields(self) -> None:
        a = self._trace_with_costs("ta", "gpt-4o", 500, 200, 0.01, 800)
        b = self._trace_with_costs("tb", "gpt-4o-mini", 500, 200, 0.001, 400)
        cmp = TraceComparison.from_traces(a, b)
        assert cmp.model_a == "gpt-4o"
        assert cmp.model_b == "gpt-4o-mini"
        assert cmp.cost_delta_usd == pytest.approx(-0.009, abs=1e-6)
        assert cmp.latency_delta_ms == pytest.approx(-400)

    def test_comparison_str(self) -> None:
        a = self._trace_with_costs("ta", "gpt-4o", 500, 200, 0.01, 800)
        b = self._trace_with_costs("tb", "gpt-4o-mini", 500, 200, 0.001, 400)
        cmp = TraceComparison.from_traces(a, b)
        output = str(cmp)
        assert "Cost" in output
        assert "Latency" in output
        assert "gpt-4o" in output


# ---------------------------------------------------------------------------
# monitor.compare() and monitor.set_token_budget() (#76, #79)
# ---------------------------------------------------------------------------


class TestMonitorMilestone4:
    def _monitor_with_spans(self, spans_config: list[dict]) -> Monitor:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        for cfg in spans_config:
            span = _make_span(**cfg)
            m.emit(span)
        time.sleep(0.1)
        return m

    def test_compare_returns_comparison(self) -> None:
        m = Monitor(auto=False)
        a = _make_trace(_make_span(trace_id="ta", model="gpt-4o", cost_usd=0.01, latency_ms=800), trace_id="ta")
        b = _make_trace(
            _make_span(trace_id="tb", span_id="s2", model="gpt-4o-mini", cost_usd=0.001, latency_ms=300),
            trace_id="tb",
        )
        cmp = m.compare(a, b)
        assert cmp.model_a == "gpt-4o"
        assert cmp.model_b == "gpt-4o-mini"

    def test_set_token_budget_tracks_tokens(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.set_token_budget(daily=1_000)
        span = _make_span(input_tokens=600, output_tokens=400)
        m.emit(span)
        assert m._session_tokens == 1000
        assert m._daily_tokens == 1000
        m.stop()

    def test_token_summary(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        m.set_token_budget(monthly=10_000, daily=1_000)
        span = _make_span(input_tokens=200, output_tokens=100)
        m.emit(span)
        summary = m.token_summary()
        assert summary["session_tokens"] == 300
        assert summary["today_tokens"] == 300
        assert summary["budget_daily"] == 1_000
        assert summary["budget_monthly"] == 10_000
        m.stop()

    def test_recommendations_returns_report(self) -> None:
        m = Monitor(storage=MemoryStorage(), auto=False)
        m.start()
        span = _make_span(input_tokens=100, output_tokens=50, cost_usd=0.001)
        m.emit(span)
        time.sleep(0.15)
        report = m.recommendations()
        assert hasattr(report, "recommendations")
        m.stop()


# ---------------------------------------------------------------------------
# Span.replay() (#78) — unit-level (no real SDK calls)
# ---------------------------------------------------------------------------


class TestTraceReplay:
    def test_replay_raises_without_messages(self) -> None:
        span = _make_span(provider="openai", model="gpt-4o")
        trace = _make_trace(span)
        with pytest.raises(ValueError, match="No messages stored"):
            trace.replay()

    def test_replay_raises_no_root_span(self) -> None:
        trace = Trace(trace_id="empty")
        with pytest.raises(ValueError, match="No root span"):
            trace.replay()

    def test_replay_raises_unsupported_provider(self) -> None:
        span = _make_span(provider="unknown-provider", model="llm-x")
        span.set_attribute("llm.messages", [{"role": "user", "content": "hello"}])
        trace = _make_trace(span)
        with pytest.raises(NotImplementedError, match="Replay is not supported"):
            trace.replay()
