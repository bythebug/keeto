"""Tests for the Event hierarchy."""

import pytest

from keeto.core.events import (
    CustomEvent,
    ErrorEvent,
    LLMRequestEndEvent,
    LLMRequestStartEvent,
    LLMStreamChunkEvent,
    RateLimitEvent,
    RetryEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)


def base_kwargs() -> dict:
    return {"trace_id": "t1", "span_id": "s1"}


class TestEventImmutability:
    def test_frozen(self) -> None:
        evt = LLMRequestStartEvent(
            **base_kwargs(),
            provider="openai",
            model="gpt-4o",
            messages=[],
        )
        with pytest.raises((ValueError, TypeError, AttributeError)):
            evt.provider = "changed"  # type: ignore[misc]

    def test_event_id_unique(self) -> None:
        a = CustomEvent(**base_kwargs(), name="x")
        b = CustomEvent(**base_kwargs(), name="x")
        assert a.event_id != b.event_id


class TestLLMRequestEvents:
    def test_start_event(self) -> None:
        evt = LLMRequestStartEvent(
            **base_kwargs(),
            provider="openai",
            model="gpt-4o",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.7,
            stream=True,
        )
        assert evt.provider == "openai"
        assert evt.model == "gpt-4o"
        assert evt.stream is True

    def test_end_event(self) -> None:
        evt = LLMRequestEndEvent(
            **base_kwargs(),
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.00045,
            latency_ms=1234.5,
            finish_reason="end_turn",
        )
        assert evt.input_tokens == 100
        assert evt.cost_usd == pytest.approx(0.00045)

    def test_stream_chunk(self) -> None:
        evt = LLMStreamChunkEvent(**base_kwargs(), chunk_index=0, content="Hello", finish_reason=None)
        assert evt.content == "Hello"


class TestToolCallEvents:
    def test_tool_call_start(self) -> None:
        evt = ToolCallStartEvent(
            **base_kwargs(),
            tool_name="search_web",
            tool_input={"query": "AI news"},
            call_id="call-abc",
        )
        assert evt.tool_name == "search_web"

    def test_tool_call_end_with_error(self) -> None:
        evt = ToolCallEndEvent(
            **base_kwargs(),
            tool_name="search_web",
            latency_ms=45.0,
            error="Connection timeout",
        )
        assert evt.error == "Connection timeout"


class TestReliabilityEvents:
    def test_retry_event(self) -> None:
        evt = RetryEvent(**base_kwargs(), attempt=2, reason="rate_limit", delay_ms=1000.0)
        assert evt.attempt == 2

    def test_rate_limit_event(self) -> None:
        evt = RateLimitEvent(**base_kwargs(), provider="openai", retry_after_s=30.0)
        assert evt.retry_after_s == 30.0

    def test_error_event(self) -> None:
        evt = ErrorEvent(
            **base_kwargs(),
            exc_type="httpx.TimeoutException",
            message="Request timed out",
            recoverable=True,
        )
        assert evt.recoverable is True


class TestCustomEvent:
    def test_custom_event(self) -> None:
        evt = CustomEvent(**base_kwargs(), name="vector-search", attributes={"results": 5})
        assert evt.name == "vector-search"
        assert evt.attributes["results"] == 5
