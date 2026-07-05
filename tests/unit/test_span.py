"""Tests for Span and Trace models."""

from datetime import UTC, datetime, timedelta

import pytest

from keeto.core.span import Span, SpanKind, SpanStatus, Trace


def make_span(**kwargs: object) -> Span:
    defaults = {"trace_id": "trace-1", "span_id": "span-1", "name": "test"}
    return Span(**(defaults | kwargs))  # type: ignore[arg-type]


class TestSpan:
    def test_defaults(self) -> None:
        span = make_span()
        assert span.status == SpanStatus.UNSET
        assert span.kind == SpanKind.CUSTOM
        assert span.end_time is None
        assert span.latency_ms is None

    def test_finish_sets_end_time(self) -> None:
        span = make_span()
        span.finish()
        assert span.end_time is not None
        assert span.status == SpanStatus.OK

    def test_finish_error(self) -> None:
        span = make_span()
        span.finish(status=SpanStatus.ERROR, status_message="oops")
        assert span.status == SpanStatus.ERROR
        assert span.status_message == "oops"

    def test_latency_ms(self) -> None:
        now = datetime.now(UTC)
        span = make_span(start_time=now)
        span.end_time = now + timedelta(milliseconds=1234)
        assert span.latency_ms == pytest.approx(1234.0, abs=1.0)

    def test_total_tokens(self) -> None:
        span = make_span(input_tokens=100, output_tokens=50)
        assert span.total_tokens == 150

    def test_total_tokens_none_when_missing(self) -> None:
        span = make_span()
        assert span.total_tokens is None

    def test_set_attribute(self) -> None:
        span = make_span()
        span.set_attribute("foo", "bar")
        assert span.attributes["foo"] == "bar"

    def test_add_event(self) -> None:
        span = make_span()
        span.add_event("my-event", {"key": "val"})
        assert len(span.events) == 1
        assert span.events[0].name == "my-event"

    def test_naive_datetime_gets_utc(self) -> None:
        naive = datetime(2024, 1, 1, 12, 0, 0)
        span = make_span(start_time=naive)
        assert span.start_time.tzinfo is not None


class TestTrace:
    def test_empty_trace(self) -> None:
        trace = Trace(trace_id="t1")
        assert trace.root_span is None
        assert trace.latency_ms is None
        assert trace.total_cost_usd == 0.0
        assert not trace.has_error

    def test_add_span(self) -> None:
        trace = Trace(trace_id="t1")
        span = make_span(trace_id="t1", span_id="s1")
        span.finish()
        trace.add_span(span)
        assert len(trace.spans) == 1
        assert trace.root_span == span

    def test_has_error(self) -> None:
        trace = Trace(trace_id="t1")
        span = make_span(trace_id="t1", span_id="s1")
        span.finish(status=SpanStatus.ERROR)
        trace.add_span(span)
        assert trace.has_error

    def test_cost_aggregation(self) -> None:
        trace = Trace(trace_id="t1")
        for i, cost in enumerate([0.001, 0.002, 0.003]):
            span = make_span(trace_id="t1", span_id=f"s{i}", cost_usd=cost)
            span.finish()
            trace.add_span(span)
        assert trace.total_cost_usd == pytest.approx(0.006)

    def test_token_aggregation(self) -> None:
        trace = Trace(trace_id="t1")
        s1 = make_span(trace_id="t1", span_id="s1", input_tokens=100, output_tokens=50)
        s2 = make_span(trace_id="t1", span_id="s2", input_tokens=200, output_tokens=75)
        s1.finish()
        s2.finish()
        trace.add_span(s1)
        trace.add_span(s2)
        assert trace.total_input_tokens == 300
        assert trace.total_output_tokens == 125
