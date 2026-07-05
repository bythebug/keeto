"""Tests for the web dashboard (issues #31–#38)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from keeto.core.span import Span, SpanStatus, Trace
from keeto.dashboard.web.server import (
    _error_rows,
    _recommendations_html,
    _trace_detail_html,
    _trace_rows,
    create_app,
)
from keeto.storage.memory import MemoryStorage

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_trace(
    trace_id: str = "abc123",
    provider: str = "openai",
    model: str = "gpt-4o",
    latency_ms: float = 500.0,
    input_tokens: int = 200,
    output_tokens: int = 80,
    cost_usd: float = 0.0012,
    error: bool = False,
    status_message: str | None = None,
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
    span.finish(
        status=SpanStatus.ERROR if error else SpanStatus.OK,
        status_message=status_message,
    )
    span.end_time = span.start_time + timedelta(milliseconds=latency_ms)
    trace.add_span(span)
    return trace


def _seed(storage: MemoryStorage, *traces: Trace) -> None:
    """Synchronously append traces to storage."""

    async def _append_all() -> None:
        for t in traces:
            for s in t.spans:
                await storage.append(s)

    asyncio.run(_append_all())


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def client(storage: MemoryStorage) -> TestClient:
    app = create_app(storage)
    return TestClient(app)


# ---------------------------------------------------------------------------
# #31 — app instantiation
# ---------------------------------------------------------------------------


class TestAppInstantiates:
    def test_create_app_returns_fastapi(self, storage: MemoryStorage) -> None:
        from fastapi import FastAPI

        app = create_app(storage)
        assert isinstance(app, FastAPI)

    def test_routes_registered(self, storage: MemoryStorage) -> None:
        app = create_app(storage)
        paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
        assert "/" in paths
        assert "/api/traces" in paths
        assert "/api/traces/{trace_id}" in paths
        assert "/api/metrics" in paths
        assert "/api/stream" in paths


# ---------------------------------------------------------------------------
# #32 — trace list page
# ---------------------------------------------------------------------------


class TestGetRoot:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200

    def test_content_type_html(self, client: TestClient) -> None:
        r = client.get("/")
        assert "text/html" in r.headers["content-type"]

    def test_contains_htmx_script(self, client: TestClient) -> None:
        r = client.get("/")
        assert "htmx" in r.text.lower()

    def test_contains_keeto_title(self, client: TestClient) -> None:
        r = client.get("/")
        assert "keeto" in r.text.lower()


class TestApiTracesEmpty:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get("/api/traces")
        assert r.status_code == 200

    def test_contains_no_traces_message(self, client: TestClient) -> None:
        r = client.get("/api/traces")
        assert "No traces" in r.text


class TestApiTracesWithData:
    def test_trace_ids_present(self, client: TestClient, storage: MemoryStorage) -> None:
        t1 = _make_trace("aabbccdd1122")
        t2 = _make_trace("eeff00112233")
        _seed(storage, t1, t2)
        r = client.get("/api/traces")
        assert "aabbccdd" in r.text
        assert "eeff0011" in r.text

    def test_row_count(self, client: TestClient, storage: MemoryStorage) -> None:
        for i in range(5):
            _seed(storage, _make_trace(f"trace{i:08d}"))
        r = client.get("/api/traces")
        assert r.text.count("<tr") == 5


# ---------------------------------------------------------------------------
# #33 — trace detail
# ---------------------------------------------------------------------------


class TestApiTraceDetail:
    def test_returns_200_for_known_trace(self, client: TestClient, storage: MemoryStorage) -> None:
        t = _make_trace("deadbeef1234")
        _seed(storage, t)
        r = client.get(f"/api/traces/{t.trace_id}")
        assert r.status_code == 200

    def test_contains_trace_id(self, client: TestClient, storage: MemoryStorage) -> None:
        t = _make_trace("cafebabe5678")
        _seed(storage, t)
        r = client.get(f"/api/traces/{t.trace_id}")
        assert t.trace_id in r.text

    def test_returns_404_for_unknown(self, client: TestClient) -> None:
        r = client.get("/api/traces/doesnotexist")
        assert r.status_code == 404

    def test_contains_model_and_provider(self, client: TestClient, storage: MemoryStorage) -> None:
        t = _make_trace("a1b2c3d4e5f6", model="claude-3-5-sonnet", provider="anthropic")
        _seed(storage, t)
        r = client.get(f"/api/traces/{t.trace_id}")
        assert "anthropic" in r.text
        assert "claude" in r.text


# ---------------------------------------------------------------------------
# #35 — metrics endpoint
# ---------------------------------------------------------------------------


class TestApiMetrics:
    def test_returns_200(self, client: TestClient) -> None:
        r = client.get("/api/metrics")
        assert r.status_code == 200

    def test_required_keys_present(self, client: TestClient) -> None:
        r = client.get("/api/metrics")
        d = r.json()
        for key in (
            "total_cost_usd",
            "today_cost_usd",
            "total_traces",
            "avg_latency_ms",
            "error_count",
            "model_breakdown",
        ):
            assert key in d, f"missing key: {key}"

    def test_empty_storage_zeros(self, client: TestClient) -> None:
        d = client.get("/api/metrics").json()
        assert d["total_traces"] == 0
        assert d["total_cost_usd"] == 0
        assert d["model_breakdown"] == []

    def test_model_breakdown_populated(self, client: TestClient, storage: MemoryStorage) -> None:
        _seed(storage, _make_trace("t1", model="gpt-4o", cost_usd=0.002))
        _seed(storage, _make_trace("t2", model="claude-3-5", provider="anthropic", cost_usd=0.004))
        d = client.get("/api/metrics").json()
        models = {m["model"] for m in d["model_breakdown"]}
        assert "gpt-4o" in models
        assert "claude-3-5" in models

    def test_error_count(self, client: TestClient, storage: MemoryStorage) -> None:
        _seed(storage, _make_trace("t1", error=True))
        _seed(storage, _make_trace("t2", error=False))
        d = client.get("/api/metrics").json()
        assert d["error_count"] == 1


# ---------------------------------------------------------------------------
# #36 — errors_only filter
# ---------------------------------------------------------------------------


class TestApiTracesErrorsOnly:
    def test_only_error_traces_returned(self, client: TestClient, storage: MemoryStorage) -> None:
        ok_trace = _make_trace("oktraceabc1", error=False)
        err_trace = _make_trace("errtracedef2", error=True)
        _seed(storage, ok_trace, err_trace)
        r = client.get("/api/traces?errors_only=1")
        assert "errtrace" in r.text
        assert "oktrace" not in r.text

    def test_no_errors_shows_placeholder(self, client: TestClient, storage: MemoryStorage) -> None:
        _seed(storage, _make_trace("t1", error=False))
        r = client.get("/api/traces?errors_only=1")
        assert "No errors" in r.text


# ---------------------------------------------------------------------------
# #37 — recommendations
# ---------------------------------------------------------------------------


class TestRecommendations:
    def test_no_data_message(self) -> None:
        html = _recommendations_html([])
        assert "No data" in html

    def test_all_ok_message(self) -> None:
        traces = [_make_trace(f"t{i}", latency_ms=200.0, cost_usd=0.001) for i in range(3)]
        html = _recommendations_html(traces)
        assert "looking good" in html.lower() or "No recommendations" in html

    def test_slow_request_warning(self) -> None:
        traces = [_make_trace("slow", latency_ms=6000.0)]
        html = _recommendations_html(traces)
        assert "5s" in html or "streaming" in html.lower()

    def test_cost_alert(self) -> None:
        traces = [_make_trace(f"t{i}", cost_usd=0.5) for i in range(3)]
        html = _recommendations_html(traces)
        assert "$" in html or "cost" in html.lower()

    def test_error_count_warning(self) -> None:
        traces = [_make_trace("e1", error=True), _make_trace("e2", error=False)]
        html = _recommendations_html(traces)
        assert "error" in html.lower()

    def test_api_recommendations_200(self, client: TestClient) -> None:
        r = client.get("/api/recommendations")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


# ---------------------------------------------------------------------------
# Fragment builder unit tests
# ---------------------------------------------------------------------------


class TestTraceRows:
    def test_empty(self) -> None:
        html = _trace_rows([])
        assert "No traces" in html

    def test_contains_trace_id_prefix(self) -> None:
        t = _make_trace("abcdef123456")
        html = _trace_rows([t])
        assert "abcdef12" in html

    def test_error_badge(self) -> None:
        t = _make_trace("e1", error=True)
        html = _trace_rows([t])
        assert "badge-err" in html

    def test_ok_badge(self) -> None:
        t = _make_trace("ok1", error=False)
        html = _trace_rows([t])
        assert "badge-ok" in html


class TestErrorRows:
    def test_empty(self) -> None:
        html = _error_rows([])
        assert "No errors" in html

    def test_filters_non_errors(self) -> None:
        traces = [_make_trace("ok"), _make_trace("err", error=True)]
        html = _error_rows(traces)
        assert "err"[:8] in html
        # ok trace id should not be in error rows
        assert "ok"[:8] not in html

    def test_status_message_shown(self) -> None:
        t = _make_trace("e1", error=True, status_message="rate limit exceeded")
        html = _error_rows([t])
        assert "rate limit exceeded" in html


class TestTraceDetailHtml:
    def test_contains_trace_id(self) -> None:
        t = _make_trace("fullid1234567890")
        html = _trace_detail_html(t)
        assert "fullid1234567890" in html

    def test_contains_provider(self) -> None:
        t = _make_trace("t1", provider="anthropic")
        html = _trace_detail_html(t)
        assert "anthropic" in html

    def test_contains_waterfall_section(self) -> None:
        t = _make_trace("t1")
        html = _trace_detail_html(t)
        assert "waterfall" in html


class TestDarkMode:
    def test_root_contains_theme_toggle_button(self) -> None:
        storage = MemoryStorage()
        client = TestClient(create_app(storage))
        resp = client.get("/")
        assert resp.status_code == 200
        assert "theme-toggle" in resp.text

    def test_root_contains_light_css_vars(self) -> None:
        storage = MemoryStorage()
        client = TestClient(create_app(storage))
        resp = client.get("/")
        assert resp.status_code == 200
        assert ".light" in resp.text or "root.light" in resp.text

    def test_root_contains_toggle_script(self) -> None:
        storage = MemoryStorage()
        client = TestClient(create_app(storage))
        resp = client.get("/")
        assert resp.status_code == 200
        assert "toggleTheme" in resp.text
        assert "localStorage" in resp.text
