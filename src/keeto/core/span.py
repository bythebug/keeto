from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SpanKind(str, Enum):
    LLM = "llm"
    TOOL = "tool"
    EMBEDDING = "embedding"
    CHAIN = "chain"
    AGENT = "agent"
    RETRIEVAL = "retrieval"
    CUSTOM = "custom"


class SpanStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    UNSET = "unset"


class SpanEvent(BaseModel):
    """A point-in-time event attached to a span."""

    name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attributes: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    """OTel-compatible span representing a single unit of work."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    kind: SpanKind = SpanKind.CUSTOM
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)
    status: SpanStatus = SpanStatus.UNSET
    status_message: str | None = None

    # AI-specific fields (populated by plugins)
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None

    @property
    def latency_ms(self) -> float | None:
        if self.end_time is None:
            return None
        delta = self.end_time - self.start_time
        return delta.total_seconds() * 1000

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append(SpanEvent(name=name, attributes=attributes or {}))

    def finish(
        self,
        status: SpanStatus = SpanStatus.OK,
        status_message: str | None = None,
        end_time: datetime | None = None,
    ) -> None:
        self.end_time = end_time or datetime.now(timezone.utc)
        self.status = status
        if status_message:
            self.status_message = status_message

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def ensure_timezone(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class Trace(BaseModel):
    """A collection of spans sharing the same trace_id."""

    trace_id: str
    spans: list[Span] = Field(default_factory=list)
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None

    @property
    def root_span(self) -> Span | None:
        return next((s for s in self.spans if s.parent_span_id is None), None)

    @property
    def latency_ms(self) -> float | None:
        root = self.root_span
        return root.latency_ms if root else None

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.spans if s.cost_usd is not None)

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.spans if s.input_tokens is not None)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.spans if s.output_tokens is not None)

    @property
    def has_error(self) -> bool:
        return any(s.status == SpanStatus.ERROR for s in self.spans)

    @property
    def provider(self) -> str | None:
        root = self.root_span
        return root.provider if root else None

    @property
    def model(self) -> str | None:
        root = self.root_span
        return root.model if root else None

    def add_span(self, span: Span) -> None:
        self.spans.append(span)
        if span.end_time:
            self.end_time = span.end_time
