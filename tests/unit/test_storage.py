"""Tests for MemoryStorage."""

from datetime import UTC, datetime, timedelta

import pytest

from keeto.core.span import Span
from keeto.storage.memory import MemoryStorage


def make_span(trace_id: str = "t1", span_id: str = "s1") -> Span:
    s = Span(trace_id=trace_id, span_id=span_id, name="test")
    s.finish()
    return s


class TestMemoryStorage:
    @pytest.mark.asyncio
    async def test_append_and_get(self) -> None:
        store = MemoryStorage()
        span = make_span()
        await store.append(span)
        trace = await store.get_trace("t1")
        assert trace is not None
        assert len(trace.spans) == 1

    @pytest.mark.asyncio
    async def test_multiple_spans_same_trace(self) -> None:
        store = MemoryStorage()
        await store.append(make_span("t1", "s1"))
        await store.append(make_span("t1", "s2"))
        trace = await store.get_trace("t1")
        assert trace is not None
        assert len(trace.spans) == 2

    @pytest.mark.asyncio
    async def test_get_missing_trace_returns_none(self) -> None:
        store = MemoryStorage()
        assert await store.get_trace("nope") is None

    @pytest.mark.asyncio
    async def test_list_traces_newest_first(self) -> None:
        store = MemoryStorage()
        for i in range(5):
            await store.append(make_span(f"t{i}", f"s{i}"))
        traces = await store.list_traces(limit=5)
        assert len(traces) == 5
        # newest (t4) should come first
        assert traces[0].trace_id == "t4"

    @pytest.mark.asyncio
    async def test_ring_buffer_evicts_oldest(self) -> None:
        store = MemoryStorage(max_traces=3)
        for i in range(5):
            await store.append(make_span(f"t{i}", f"s{i}"))
        assert len(store) == 3
        # t0 and t1 should have been evicted
        assert await store.get_trace("t0") is None
        assert await store.get_trace("t4") is not None

    @pytest.mark.asyncio
    async def test_purge(self) -> None:
        store = MemoryStorage()
        old_span = Span(trace_id="old", span_id="s1", name="test")
        old_span.start_time = datetime.now(UTC) - timedelta(days=10)
        old_span.finish()
        new_span = make_span("new", "s2")

        await store.append(old_span)
        await store.append(new_span)

        cutoff = datetime.now(UTC) - timedelta(days=1)
        purged = await store.purge(older_than=cutoff)

        assert purged == 1
        assert await store.get_trace("old") is None
        assert await store.get_trace("new") is not None

    @pytest.mark.asyncio
    async def test_pagination(self) -> None:
        store = MemoryStorage()
        for i in range(10):
            await store.append(make_span(f"t{i}", f"s{i}"))
        page1 = await store.list_traces(limit=3, offset=0)
        page2 = await store.list_traces(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert {t.trace_id for t in page1}.isdisjoint({t.trace_id for t in page2})
