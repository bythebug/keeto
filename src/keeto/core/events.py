from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


def _uid() -> str:
    return str(uuid.uuid4())


class BaseEvent(BaseModel):
    """Root of the Keeto event hierarchy. All events are immutable after creation."""

    event_id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    trace_id: str
    span_id: str

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# LLM request lifecycle
# ---------------------------------------------------------------------------


class LLMRequestStartEvent(BaseEvent):
    provider: str
    model: str
    messages: list[dict[str, Any]]
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class LLMRequestEndEvent(BaseEvent):
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: float
    finish_reason: str | None = None
    response_text: str | None = None


class LLMStreamChunkEvent(BaseEvent):
    chunk_index: int
    content: str
    finish_reason: str | None = None


# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------


class ToolCallStartEvent(BaseEvent):
    tool_name: str
    tool_input: dict[str, Any]
    call_id: str | None = None


class ToolCallEndEvent(BaseEvent):
    tool_name: str
    call_id: str | None = None
    tool_output: Any = None
    latency_ms: float
    error: str | None = None


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class EmbeddingRequestEvent(BaseEvent):
    provider: str
    model: str
    input_count: int
    dimensions: int | None = None
    input_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: float


# ---------------------------------------------------------------------------
# Reliability events
# ---------------------------------------------------------------------------


class RetryEvent(BaseEvent):
    attempt: int
    reason: str
    delay_ms: float


class RateLimitEvent(BaseEvent):
    provider: str
    retry_after_s: float | None = None


class ErrorEvent(BaseEvent):
    exc_type: str
    message: str
    recoverable: bool = False
    traceback: str | None = None


# ---------------------------------------------------------------------------
# User-defined
# ---------------------------------------------------------------------------


class CustomEvent(BaseEvent):
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)


# All concrete event types for isinstance checks and union types
AnyEvent = (
    LLMRequestStartEvent
    | LLMRequestEndEvent
    | LLMStreamChunkEvent
    | ToolCallStartEvent
    | ToolCallEndEvent
    | EmbeddingRequestEvent
    | RetryEvent
    | RateLimitEvent
    | ErrorEvent
    | CustomEvent
)
