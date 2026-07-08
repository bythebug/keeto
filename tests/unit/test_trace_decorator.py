"""Tests for the @trace decorator and pipeline_breakdown()."""

from __future__ import annotations

import asyncio
import time

import pytest

import keeto
from keeto.core.monitor import Monitor, _kind_from_name
from keeto.core.span import SpanKind, SpanStatus
from keeto.storage.memory import MemoryStorage


@pytest.fixture
def m() -> Monitor:
    mon = Monitor(storage=MemoryStorage(), auto=False)
    mon.start()
    yield mon
    mon.stop()


# ---------------------------------------------------------------------------
# _kind_from_name
# ---------------------------------------------------------------------------


class TestKindFromName:
    def test_embedding(self) -> None:
        assert _kind_from_name("embedding") == SpanKind.EMBEDDING
        assert _kind_from_name("embed") == SpanKind.EMBEDDING
        assert _kind_from_name("embeddings") == SpanKind.EMBEDDING

    def test_retrieval(self) -> None:
        assert _kind_from_name("retrieval") == SpanKind.RETRIEVAL
        assert _kind_from_name("search") == SpanKind.RETRIEVAL
        assert _kind_from_name("vector-search") == SpanKind.RETRIEVAL
        assert _kind_from_name("rerank") == SpanKind.RETRIEVAL

    def test_llm(self) -> None:
        assert _kind_from_name("llm") == SpanKind.LLM
        assert _kind_from_name("generate") == SpanKind.LLM
        assert _kind_from_name("completion") == SpanKind.LLM
        assert _kind_from_name("chat") == SpanKind.LLM

    def test_tool(self) -> None:
        assert _kind_from_name("tool") == SpanKind.TOOL
        assert _kind_from_name("tool-call") == SpanKind.TOOL

    def test_custom_fallback(self) -> None:
        assert _kind_from_name("prompt-build") == SpanKind.CUSTOM
        assert _kind_from_name("unknown") == SpanKind.CUSTOM


# ---------------------------------------------------------------------------
# monitor.trace() — sync
# ---------------------------------------------------------------------------


class TestTraceDecoratorSync:
    def test_sync_function_is_traced(self, m: Monitor) -> None:
        @m.trace("embedding")
        def embed(text: str) -> str:
            return text.upper()

        result = embed("hello")
        assert result == "HELLO"

        time.sleep(0.15)
        traces = asyncio.run(m._storage.list_traces())
        assert len(traces) == 1
        span = traces[0].spans[0]
        assert span.name == "embedding"
        assert span.kind == SpanKind.EMBEDDING
        assert span.status == SpanStatus.OK
        assert span.latency_ms is not None

    def test_sync_error_recorded(self, m: Monitor) -> None:
        @m.trace("retrieval")
        def search(q: str) -> list[str]:
            raise RuntimeError("db down")

        with pytest.raises(RuntimeError):
            search("query")

        time.sleep(0.15)
        traces = asyncio.run(m._storage.list_traces())
        assert traces[0].spans[0].status == SpanStatus.ERROR

    def test_explicit_kind_overrides_auto(self, m: Monitor) -> None:
        @m.trace("my-stage", kind=SpanKind.CHAIN)
        def pipeline() -> None:
            pass

        pipeline()
        time.sleep(0.15)
        traces = asyncio.run(m._storage.list_traces())
        assert traces[0].spans[0].kind == SpanKind.CHAIN

    def test_wrapped_function_preserves_metadata(self, m: Monitor) -> None:
        @m.trace("embed")
        def embed_text(text: str) -> str:
            """Embed a text string."""
            return text

        assert embed_text.__name__ == "embed_text"
        assert embed_text.__doc__ == "Embed a text string."


# ---------------------------------------------------------------------------
# monitor.trace() — async
# ---------------------------------------------------------------------------


class TestTraceDecoratorAsync:
    def test_async_function_is_traced(self, m: Monitor) -> None:
        @m.trace("retrieval")
        async def search(q: str) -> list[str]:
            await asyncio.sleep(0)
            return ["result"]

        result = asyncio.run(search("test"))
        assert result == ["result"]

        time.sleep(0.15)
        traces = asyncio.run(m._storage.list_traces())
        assert len(traces) == 1
        span = traces[0].spans[0]
        assert span.name == "retrieval"
        assert span.kind == SpanKind.RETRIEVAL
        assert span.status == SpanStatus.OK

    def test_async_error_recorded(self, m: Monitor) -> None:
        @m.trace("llm")
        async def generate(prompt: str) -> str:
            raise ValueError("token limit exceeded")

        with pytest.raises(ValueError):
            asyncio.run(generate("hi"))

        time.sleep(0.15)
        traces = asyncio.run(m._storage.list_traces())
        assert traces[0].spans[0].status == SpanStatus.ERROR

    def test_async_preserves_metadata(self, m: Monitor) -> None:
        @m.trace("generate")
        async def call_llm(prompt: str) -> str:
            """Call an LLM."""
            return prompt

        assert call_llm.__name__ == "call_llm"
        assert call_llm.__doc__ == "Call an LLM."


# ---------------------------------------------------------------------------
# Multi-stage pipeline — nested trace context
# ---------------------------------------------------------------------------


class TestPipelineTracing:
    def test_sequential_stages_share_trace(self, m: Monitor) -> None:
        @m.trace("embedding")
        def embed(text: str) -> list[float]:
            return [0.1, 0.2]

        @m.trace("retrieval")
        def search(vec: list[float]) -> list[str]:
            return ["doc1"]

        @m.trace("llm")
        def generate(docs: list[str]) -> str:
            return "answer"

        with m.span("rag-pipeline"):
            vecs = embed("query")
            docs = search(vecs)
            generate(docs)

        time.sleep(0.2)
        traces = asyncio.run(m._storage.list_traces())
        assert len(traces) == 1
        names = {s.name for s in traces[0].spans}
        assert {"rag-pipeline", "embedding", "retrieval", "llm"} == names

    def test_child_spans_have_parent(self, m: Monitor) -> None:
        @m.trace("embed")
        def embed() -> None:
            pass

        with m.span("root"):
            embed()

        time.sleep(0.2)
        traces = asyncio.run(m._storage.list_traces())
        spans = {s.name: s for s in traces[0].spans}
        root_id = spans["root"].span_id
        assert spans["embed"].parent_span_id == root_id


# ---------------------------------------------------------------------------
# Module-level trace() convenience
# ---------------------------------------------------------------------------


class TestModuleLevelTrace:
    def test_module_level_trace_is_callable(self) -> None:
        # Just verify it returns a decorator without crashing
        decorator = keeto.trace("embedding")
        assert callable(decorator)

    def test_module_level_trace_in_all(self) -> None:
        assert "trace" in keeto.__all__


# ---------------------------------------------------------------------------
# pipeline_breakdown()
# ---------------------------------------------------------------------------


class TestPipelineBreakdown:
    def test_breakdown_no_traces(self, m: Monitor, capsys) -> None:
        # Should not raise; prints a "no traces" message
        m.pipeline_breakdown()

    def test_breakdown_shows_stages(self, m: Monitor, capsys) -> None:
        @m.trace("embed")
        def embed() -> None:
            time.sleep(0.01)

        @m.trace("search")
        def search() -> None:
            time.sleep(0.01)

        with m.span("pipeline"):
            embed()
            search()

        time.sleep(0.2)
        traces = asyncio.run(m._storage.list_traces())
        assert traces  # pipeline_breakdown uses storage, just verify no exception
        m.pipeline_breakdown(trace=traces[0])

    def test_breakdown_with_explicit_trace(self, m: Monitor) -> None:
        @m.trace("llm")
        def gen() -> None:
            pass

        gen()
        time.sleep(0.15)
        traces = asyncio.run(m._storage.list_traces())
        # Should not raise
        m.pipeline_breakdown(trace=traces[0])
