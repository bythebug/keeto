"""Tests for the async event pipeline."""

import asyncio
import time

import pytest
from keeto.core.pipeline import Pipeline
from keeto.core.span import Span, SpanStatus
from keeto.storage.memory import MemoryStorage


def make_span(trace_id: str = "t1", span_id: str = "s1") -> Span:
    s = Span(trace_id=trace_id, span_id=span_id, name="test")
    s.finish()
    return s


class TestPipeline:
    def test_emit_before_start_is_noop(self) -> None:
        store = MemoryStorage()
        pipe = Pipeline(store)
        # Should not raise
        pipe.emit(make_span())

    def test_start_stop(self) -> None:
        store = MemoryStorage()
        pipe = Pipeline(store)
        pipe.start()
        assert pipe._started
        pipe.stop()

    def test_spans_reach_storage(self) -> None:
        store = MemoryStorage()
        pipe = Pipeline(store)
        pipe.start()

        for i in range(5):
            pipe.emit(make_span(f"t{i}", f"s{i}"))

        # Give the background worker time to flush (>50ms batch interval)
        time.sleep(0.2)
        pipe.stop()

        assert len(store) == 5

    def test_multiple_spans_same_trace(self) -> None:
        store = MemoryStorage()
        pipe = Pipeline(store)
        pipe.start()

        pipe.emit(make_span("trace-a", "span-1"))
        pipe.emit(make_span("trace-a", "span-2"))
        time.sleep(0.2)
        pipe.stop()

        trace = asyncio.run(store.get_trace("trace-a"))
        assert trace is not None
        assert len(trace.spans) == 2

    def test_double_start_is_idempotent(self) -> None:
        store = MemoryStorage()
        pipe = Pipeline(store)
        pipe.start()
        thread1 = pipe._thread
        pipe.start()  # second call should be noop
        assert pipe._thread is thread1
        pipe.stop()
