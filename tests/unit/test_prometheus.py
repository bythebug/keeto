"""Tests for Prometheus metrics exporter — issue #85."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from keeto.core.span import Span, SpanKind, SpanStatus, Trace
from keeto.exporters.prometheus import generate_prometheus_text


def _make_trace(
    trace_id: str = "t1",
    provider: str = "openai",
    model: str = "gpt-4o",
    latency_ms: float = 500.0,
    input_tokens: int = 200,
    output_tokens: int = 60,
    cost_usd: float = 0.002,
    error: bool = False,
) -> Trace:
    now = datetime.now(UTC)
    span = Span(
        trace_id=trace_id,
        span_id="s1",
        name="openai.chat",
        kind=SpanKind.LLM,
        start_time=now,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    span.finish(
        status=SpanStatus.ERROR if error else SpanStatus.OK,
        end_time=now + timedelta(milliseconds=latency_ms),
    )
    trace = Trace(trace_id=trace_id, start_time=now)
    trace.add_span(span)
    return trace


class TestGeneratePrometheusText:
    def test_contains_required_metric_families(self) -> None:
        text = generate_prometheus_text([_make_trace()])
        assert "keeto_requests_total" in text
        assert "keeto_request_duration_seconds" in text
        assert "keeto_tokens_total" in text
        assert "keeto_cost_usd_total" in text

    def test_labels_present(self) -> None:
        text = generate_prometheus_text([_make_trace(provider="anthropic", model="claude-3-5")])
        assert 'provider="anthropic"' in text
        assert 'model="claude-3-5"' in text

    def test_request_count(self) -> None:
        traces = [_make_trace(f"t{i}") for i in range(3)]
        text = generate_prometheus_text(traces)
        # All three spans have provider=openai, model=gpt-4o, status=ok
        assert 'keeto_requests_total{provider="openai",model="gpt-4o",status="ok"} 3' in text

    def test_error_counter(self) -> None:
        traces = [_make_trace("t1", error=True)]
        text = generate_prometheus_text(traces)
        assert "keeto_errors_total" in text
        assert 'provider="openai"' in text

    def test_token_counters(self) -> None:
        traces = [_make_trace("t1", input_tokens=300, output_tokens=100)]
        text = generate_prometheus_text(traces)
        assert 'type="input"' in text
        assert 'type="output"' in text
        assert "300" in text
        assert "100" in text

    def test_empty_traces_returns_headers_only(self) -> None:
        text = generate_prometheus_text([])
        # Should have HELP/TYPE lines but no data lines
        assert "# HELP" in text
        assert "# TYPE" in text
        # No label-value pairs
        for line in text.splitlines():
            if line and not line.startswith("#"):
                pytest.fail(f"Unexpected data line with empty traces: {line!r}")

    def test_text_ends_with_newline(self) -> None:
        assert generate_prometheus_text([_make_trace()]).endswith("\n")

    def test_multiple_providers(self) -> None:
        traces = [
            _make_trace("t1", provider="openai"),
            _make_trace("t2", provider="anthropic"),
        ]
        text = generate_prometheus_text(traces)
        assert 'provider="openai"' in text
        assert 'provider="anthropic"' in text
