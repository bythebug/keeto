from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from keeto.core.context import get_current_span_id, get_current_trace_id, new_span_id, new_trace_id
from keeto.core.span import Span, SpanKind, SpanStatus
from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor


def _infer_provider(model: str, params: dict[str, Any]) -> str:
    provider = params.get("custom_llm_provider", "")
    if provider:
        return str(provider)
    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3") or model.startswith("o4"):
        return "openai"
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith("gemini"):
        return "google"
    if model.startswith("ollama"):
        return "ollama"
    return "litellm"


class _LiteLLMLogger:
    def __init__(self, plugin: LiteLLMPlugin) -> None:
        self._plugin = plugin

    def _build_span(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
        status: SpanStatus,
        error: str | None = None,
    ) -> Span:
        model = str(kwargs.get("model", ""))
        litellm_params = kwargs.get("litellm_params") or {}
        provider = _infer_provider(model, litellm_params)

        trace_id = get_current_trace_id() or new_trace_id()
        span_id = get_current_span_id() or new_span_id()

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            name="litellm.completion",
            kind=SpanKind.LLM,
            provider=provider,
            model=model,
        )

        latency_ms = (end_time - start_time).total_seconds() * 1000
        span.set_attribute("llm.latency_ms", latency_ms)

        if response_obj is not None and hasattr(response_obj, "usage") and response_obj.usage:
            usage = response_obj.usage
            span.input_tokens = getattr(usage, "prompt_tokens", None)
            span.output_tokens = getattr(usage, "completion_tokens", None)

        # Issue #60: use LiteLLM's own cost calculation when available
        response_cost = kwargs.get("response_cost")
        if response_cost is not None:
            span.cost_usd = float(response_cost)
        elif span.input_tokens is not None and span.output_tokens is not None:
            from keeto._pricing import cost_usd
            span.cost_usd = cost_usd(provider, model, span.input_tokens, span.output_tokens)

        messages = kwargs.get("messages") or []
        span.set_attribute("llm.message_count", len(messages))

        span.finish(status=status, status_message=error)
        return span

    def log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        span = self._build_span(kwargs, response_obj, start_time, end_time, SpanStatus.OK)
        self._plugin._emit(span)

    def log_failure_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        error = str(kwargs.get("exception", "unknown error"))
        span = self._build_span(kwargs, response_obj, start_time, end_time, SpanStatus.ERROR, error)
        self._plugin._emit(span)

    async def async_log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        self.log_success_event(kwargs, response_obj, start_time, end_time)

    async def async_log_failure_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        self.log_failure_event(kwargs, response_obj, start_time, end_time)


class LiteLLMPlugin(Plugin):
    name: ClassVar[str] = "litellm"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._logger: _LiteLLMLogger | None = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        try:
            import litellm
        except ImportError:
            return
        self._logger = _LiteLLMLogger(self)
        litellm.callbacks = getattr(litellm, "callbacks", [])
        if self._logger not in litellm.callbacks:
            litellm.callbacks.append(self._logger)

    def uninstall(self) -> None:
        if self._logger is None:
            return
        try:
            import litellm
            if self._logger in litellm.callbacks:
                litellm.callbacks.remove(self._logger)
        except ImportError:
            pass
        self._logger = None

    def _emit(self, span: Span) -> None:
        if self._monitor:
            self._monitor.emit(span)
