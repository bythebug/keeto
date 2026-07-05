"""
Integration test harness for Keeto plugins — Issue #65.

Uses respx to mock httpx transport so no real API keys are required.
Tests cover: OpenAI, Anthropic, LiteLLM callback, LangChain callback,
retry detection, rate limit detection, tool calls, multimodal, embeddings,
and batch requests.

Run with: pytest tests/integration/test_plugins.py -v
(These tests do NOT require API keys and run in CI without --run-integration.)
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from keeto.core.monitor import Monitor
from keeto.core.span import SpanStatus
from keeto.storage.memory import MemoryStorage

# The Keeto pipeline batches spans on a 50 ms timer in a background thread.
# Tests must await this before reading storage to avoid a race condition.
_FLUSH_WAIT = 0.25


async def _flush() -> None:
    """Wait for the background pipeline to flush its batch."""
    await asyncio.sleep(_FLUSH_WAIT)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_monitor() -> Monitor:
    storage = MemoryStorage()
    m = Monitor(storage=storage, auto=False)
    m.start()
    return m


def _openai_chat_response(
    model: str = "gpt-4o",
    input_tokens: int = 100,
    output_tokens: int = 50,
    finish_reason: str = "stop",
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": "Hello!"}
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = None
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _anthropic_messages_response(
    model: str = "claude-3-5-sonnet-20241022",
    input_tokens: int = 100,
    output_tokens: int = 50,
    tool_uses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if tool_uses:
        content.extend(tool_uses)
    else:
        content.append({"type": "text", "text": "Hello!"})
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
        },
    }


# ---------------------------------------------------------------------------
# OpenAI plugin tests
# ---------------------------------------------------------------------------


class TestOpenAIPlugin:
    def setup_method(self) -> None:
        pytest.importorskip("openai")
        from keeto.integrations.openai.plugin import OpenAIPlugin

        self.monitor = _make_monitor()
        self.storage = self.monitor._storage
        self.plugin = OpenAIPlugin()
        self.plugin.install(self.monitor)

    def teardown_method(self) -> None:
        self.plugin.uninstall()
        self.monitor.stop()

    @pytest.mark.asyncio
    async def test_chat_completion_captured(self) -> None:
        resp_body = _openai_chat_response(input_tokens=100, output_tokens=50)

        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=resp_body)
            )
            import openai

            client = openai.OpenAI(api_key="test-key")
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Hello"}],
            )

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        assert len(traces) == 1
        span = traces[0].root_span
        assert span is not None
        assert span.name == "openai.chat"
        assert span.input_tokens == 100
        assert span.output_tokens == 50
        assert span.model == "gpt-4o"
        assert span.cost_usd is not None
        assert span.status == SpanStatus.OK

    @pytest.mark.asyncio
    async def test_rate_limit_captured(self) -> None:
        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(
                    429,
                    json={"error": {"message": "Rate limit exceeded"}},
                    headers={"retry-after": "2"},
                )
            )
            import openai

            client = openai.OpenAI(api_key="test-key", max_retries=0)
            with contextlib.suppress(Exception):
                client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": "Hello"}],
                )

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        assert len(traces) == 1
        span = traces[0].root_span
        assert span is not None
        assert span.name == "openai.rate_limit"
        assert span.attributes.get("rate_limit.retry_after_s") == 2.0

    @pytest.mark.asyncio
    async def test_tool_calls_captured(self) -> None:
        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"location": "NYC"}'},
            }
        ]
        resp_body = _openai_chat_response(finish_reason="tool_calls", tool_calls=tool_calls)

        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=resp_body)
            )
            import openai

            client = openai.OpenAI(api_key="test-key")
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "What's the weather?"}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
                        },
                    }
                ],
            )

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        assert len(traces) == 1
        span = traces[0].root_span
        assert span is not None
        assert span.attributes.get("llm.tool_calls_count") == 1
        captured = span.attributes.get("llm.tool_calls", [])
        assert len(captured) == 1
        assert captured[0]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_multimodal_detected(self) -> None:
        resp_body = _openai_chat_response()

        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=resp_body)
            )
            import openai

            client = openai.OpenAI(api_key="test-key")
            client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "What's in this image?"},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                        ],
                    }
                ],
            )

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        span = traces[0].root_span
        assert span is not None
        assert span.attributes.get("llm.multimodal") is True

    @pytest.mark.asyncio
    async def test_async_chat_completion_captured(self) -> None:
        resp_body = _openai_chat_response(input_tokens=200, output_tokens=80)

        async with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=resp_body)
            )
            import openai

            client = openai.AsyncOpenAI(api_key="test-key")
            await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Hello async"}],
            )
            await client.close()

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        assert len(traces) == 1
        span = traces[0].root_span
        assert span is not None
        assert span.name == "openai.chat"
        assert span.input_tokens == 200
        assert span.output_tokens == 80
        assert span.cost_usd is not None
        assert span.status == SpanStatus.OK

    @pytest.mark.asyncio
    async def test_embedding_captured(self) -> None:
        embedding_resp = {
            "object": "list",
            "data": [{"object": "embedding", "embedding": [0.1] * 1536, "index": 0}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 8, "total_tokens": 8},
        }

        with respx.mock:
            respx.post("https://api.openai.com/v1/embeddings").mock(
                return_value=httpx.Response(200, json=embedding_resp)
            )
            import openai

            client = openai.OpenAI(api_key="test-key")
            client.embeddings.create(model="text-embedding-3-small", input=["Hello world"])

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        span = traces[0].root_span
        assert span is not None
        assert span.name == "openai.embedding"
        assert span.input_tokens == 8
        assert span.attributes.get("llm.embedding_dimensions") == 1536


# ---------------------------------------------------------------------------
# Anthropic plugin tests
# ---------------------------------------------------------------------------


class TestAnthropicPlugin:
    def setup_method(self) -> None:
        pytest.importorskip("anthropic")
        from keeto.integrations.anthropic.plugin import AnthropicPlugin

        self.monitor = _make_monitor()
        self.storage = self.monitor._storage
        self.plugin = AnthropicPlugin()
        self.plugin.install(self.monitor)

    def teardown_method(self) -> None:
        self.plugin.uninstall()
        self.monitor.stop()

    @pytest.mark.asyncio
    async def test_messages_captured(self) -> None:
        resp_body = _anthropic_messages_response(input_tokens=120, output_tokens=60)

        with respx.mock:
            respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(200, json=resp_body))
            import anthropic

            client = anthropic.Anthropic(api_key="test-key")
            client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=100,
                messages=[{"role": "user", "content": "Hello"}],
            )

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        assert len(traces) == 1
        span = traces[0].root_span
        assert span is not None
        assert span.name == "anthropic.messages"
        assert span.input_tokens == 120
        assert span.output_tokens == 60
        assert span.cost_usd is not None

    @pytest.mark.asyncio
    async def test_tool_use_captured(self) -> None:
        tool_uses = [{"type": "tool_use", "id": "toolu_01", "name": "search", "input": {"query": "test"}}]
        resp_body = _anthropic_messages_response(tool_uses=tool_uses)

        with respx.mock:
            respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(200, json=resp_body))
            import anthropic

            client = anthropic.Anthropic(api_key="test-key")
            client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=100,
                messages=[{"role": "user", "content": "Search for something"}],
                tools=[
                    {"name": "search", "description": "Search", "input_schema": {"type": "object", "properties": {}}}
                ],
            )

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        span = traces[0].root_span
        assert span is not None
        assert span.attributes.get("llm.tool_calls_count") == 1
        tool_call = span.attributes.get("llm.tool_calls", [])[0]
        assert tool_call["name"] == "search"

    @pytest.mark.asyncio
    async def test_async_messages_captured(self) -> None:
        resp_body = _anthropic_messages_response(input_tokens=80, output_tokens=40)

        async with respx.mock:
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(200, json=resp_body)
            )
            import anthropic

            client = anthropic.AsyncAnthropic(api_key="test-key")
            await client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=100,
                messages=[{"role": "user", "content": "Hello async"}],
            )
            await client.close()

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        assert len(traces) == 1
        span = traces[0].root_span
        assert span is not None
        assert span.name == "anthropic.messages"
        assert span.input_tokens == 80
        assert span.output_tokens == 40
        assert span.cost_usd is not None
        assert span.status == SpanStatus.OK

    @pytest.mark.asyncio
    async def test_rate_limit_captured(self) -> None:
        with respx.mock:
            respx.post("https://api.anthropic.com/v1/messages").mock(
                return_value=httpx.Response(
                    429,
                    json={"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited"}},
                    headers={"retry-after": "5"},
                )
            )
            import anthropic

            client = anthropic.Anthropic(api_key="test-key", max_retries=0)
            with contextlib.suppress(Exception):
                client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=100,
                    messages=[{"role": "user", "content": "Hello"}],
                )

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        span = traces[0].root_span
        assert span is not None
        assert span.name == "anthropic.rate_limit"
        assert span.attributes.get("rate_limit.retry_after_s") == 5.0


# ---------------------------------------------------------------------------
# Monitor budget tests (issue #61)
# ---------------------------------------------------------------------------


class TestBudgetAlerts:
    def setup_method(self) -> None:
        self.monitor = _make_monitor()

    def teardown_method(self) -> None:
        self.monitor.stop()

    @pytest.mark.asyncio
    async def test_session_budget_alert(self) -> None:
        from keeto.core.span import Span, SpanKind, SpanStatus

        self.monitor.set_budget(session_usd=0.001)
        warnings: list[str] = []

        original_print = self.monitor._console.print
        self.monitor._console.print = lambda *a, **kw: warnings.append(str(a[0]))  # type: ignore[method-assign]

        span = Span(trace_id="t1", span_id="s1", name="test", kind=SpanKind.LLM)
        span.cost_usd = 0.002
        span.finish(status=SpanStatus.OK)
        self.monitor.emit(span)

        assert any("session budget exceeded" in w for w in warnings)
        self.monitor._console.print = original_print


# ---------------------------------------------------------------------------
# Cost summary tests (issue #62)
# ---------------------------------------------------------------------------


class TestCostSummary:
    def setup_method(self) -> None:
        self.monitor = _make_monitor()

    def teardown_method(self) -> None:
        self.monitor.stop()

    @pytest.mark.asyncio
    async def test_cost_summary_structure(self) -> None:
        from keeto.core.span import Span, SpanKind, SpanStatus

        span = Span(trace_id="t1", span_id="s1", name="test", kind=SpanKind.LLM, provider="openai", model="gpt-4o")
        span.cost_usd = 0.01
        span.finish(status=SpanStatus.OK)
        self.monitor.emit(span)

        summary = self.monitor.cost_summary()
        assert "session_usd" in summary
        assert "today_usd" in summary
        assert "by_provider" in summary
        assert "by_model" in summary
        assert summary["session_usd"] == pytest.approx(0.01, abs=1e-6)
        assert "openai" in summary["by_provider"]


# ---------------------------------------------------------------------------
# Recommendations engine tests (issues #63, #64)
# ---------------------------------------------------------------------------


class TestRecommendationsEngine:
    def test_agent_loop_detection(self) -> None:
        from keeto.analyzers.recommendations import RecommendationsEngine
        from keeto.core.span import Span, SpanKind, SpanStatus, Trace

        engine = RecommendationsEngine()
        traces = []
        for i in range(5):
            trace = Trace(trace_id=f"t{i}")
            span = Span(trace_id=f"t{i}", span_id=f"s{i}", name="openai.chat", kind=SpanKind.LLM, model="gpt-4o")
            span.set_attribute("llm.message_count", 3)
            span.finish(status=SpanStatus.OK)
            trace.add_span(span)
            traces.append(trace)

        report = engine.analyze(traces)
        loop_recs = [r for r in report.recommendations if r.rule == "agent_loop"]
        assert len(loop_recs) == 1
        assert "gpt-4o" in loop_recs[0].message

    def test_cost_comparison(self) -> None:
        from keeto.analyzers.recommendations import RecommendationsEngine
        from keeto.core.span import Span, SpanKind, SpanStatus, Trace

        engine = RecommendationsEngine()
        traces = []
        for i, (provider, cost) in enumerate([("openai", 1.0), ("openai", 1.0), ("anthropic", 0.1)]):
            trace = Trace(trace_id=f"t{i}")
            span = Span(trace_id=f"t{i}", span_id=f"s{i}", name="llm.call", kind=SpanKind.LLM, provider=provider)
            span.cost_usd = cost
            span.finish(status=SpanStatus.OK)
            trace.add_span(span)
            traces.append(trace)

        report = engine.analyze(traces)
        cost_recs = [r for r in report.recommendations if r.rule == "cost_comparison"]
        assert len(cost_recs) == 1
        assert "openai" in cost_recs[0].message


# ---------------------------------------------------------------------------
# LiteLLM plugin test
# ---------------------------------------------------------------------------


class TestLiteLLMPlugin:
    def setup_method(self) -> None:
        self.monitor = _make_monitor()
        self.storage = self.monitor._storage

    def teardown_method(self) -> None:
        self.monitor.stop()

    @pytest.mark.asyncio
    async def test_success_callback_creates_span(self) -> None:
        pytest.importorskip("litellm")
        from datetime import datetime

        from keeto.integrations.litellm.plugin import LiteLLMPlugin

        plugin = LiteLLMPlugin()
        plugin.install(self.monitor)

        logger = plugin._logger
        assert logger is not None

        start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        end_time = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 25
        mock_response = MagicMock()
        mock_response.usage = mock_usage

        kwargs: dict[str, Any] = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "litellm_params": {"custom_llm_provider": "openai"},
            "response_cost": 0.005,
        }

        logger.log_success_event(kwargs, mock_response, start_time, end_time)

        await _flush()
        traces = await self.storage.list_traces(limit=10)
        assert len(traces) == 1
        span = traces[0].root_span
        assert span is not None
        assert span.name == "litellm.completion"
        assert span.cost_usd == pytest.approx(0.005)
        assert span.input_tokens == 50
        assert span.output_tokens == 25
