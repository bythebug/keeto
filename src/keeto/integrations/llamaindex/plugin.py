from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from keeto.core.context import get_current_span_id, get_current_trace_id, new_span_id, new_trace_id
from keeto.core.span import Span, SpanKind, SpanStatus
from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor


class LlamaIndexPlugin(Plugin):
    name: ClassVar[str] = "llamaindex"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._spans: dict[str, Span] = {}
        self._handler: Any = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        try:
            from llama_index.core.instrumentation import get_dispatcher
            from llama_index.core.instrumentation.event_handlers import BaseEventHandler

            class _KeetoEventHandler(BaseEventHandler):  # type: ignore[misc]
                def __init__(inner_self) -> None:
                    super().__init__()
                    inner_self._plugin = self

                @classmethod
                def class_name(cls) -> str:
                    return "KeetoEventHandler"

                def handle(inner_self, event: Any) -> None:
                    inner_self._plugin._handle_event(event)

            self._handler = _KeetoEventHandler()
            dispatcher = get_dispatcher()
            if self._handler not in dispatcher.event_handlers:
                dispatcher.add_event_handler(self._handler)
        except ImportError:
            pass

    def uninstall(self) -> None:
        if self._handler is None:
            return
        try:
            from llama_index.core.instrumentation import get_dispatcher

            dispatcher = get_dispatcher()
            handlers = dispatcher.event_handlers
            if self._handler in handlers:
                handlers.remove(self._handler)
        except (ImportError, AttributeError):
            pass
        self._handler = None
        self._spans.clear()

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    def _handle_event(self, event: Any) -> None:
        event_type = type(event).__name__

        if event_type in ("LLMChatStartEvent", "LLMCompletionStartEvent"):
            self._on_llm_start(event)
        elif event_type in ("LLMChatEndEvent", "LLMCompletionEndEvent"):
            self._on_llm_end(event)
        elif event_type == "EmbeddingStartEvent":
            self._on_embedding_start(event)
        elif event_type == "EmbeddingEndEvent":
            self._on_embedding_end(event)
        # Span-lifecycle events signal chain/agent boundaries.
        elif event_type == "SpanDropEvent":
            self._on_span_drop(event)

    def _span_key(self, event: Any) -> str:
        span_id = getattr(event, "span_id", None)
        if span_id is not None:
            return str(span_id)
        return str(id(event))

    def _on_llm_start(self, event: Any) -> None:
        key = self._span_key(event)
        trace_id = get_current_trace_id() or new_trace_id()
        span_id = new_span_id()
        parent_span_id = get_current_span_id()

        model: str | None = None
        messages = getattr(event, "messages", None)
        msg_count = len(messages) if messages else 0

        # model_dict may be available on serialized LLM
        llm = getattr(event, "llm", None)
        if llm is not None:
            model = getattr(llm, "model", None) or getattr(llm, "model_name", None)

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name="llamaindex.llm",
            kind=SpanKind.LLM,
            model=model,
        )
        span.set_attribute("llm.message_count", msg_count)
        self._spans[key] = span

    def _on_llm_end(self, event: Any) -> None:
        key = self._span_key(event)
        span = self._spans.pop(key, None)
        if span is None:
            return

        response = getattr(event, "response", None)
        if response is not None:
            raw = getattr(response, "raw", None) or {}
            usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
            span.input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
            span.output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")

        span.finish(status=SpanStatus.OK)
        if self._monitor:
            self._monitor.emit(span)

    def _on_embedding_start(self, event: Any) -> None:
        key = self._span_key(event)
        trace_id = get_current_trace_id() or new_trace_id()
        span_id = new_span_id()
        parent_span_id = get_current_span_id()

        getattr(event, "model_dict", {})
        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name="llamaindex.embedding",
            kind=SpanKind.EMBEDDING,
        )
        chunk_count = getattr(event, "chunks", None)
        if chunk_count is not None:
            span.set_attribute("embedding.chunk_count", len(chunk_count))
        self._spans[key] = span

    def _on_embedding_end(self, event: Any) -> None:
        key = self._span_key(event)
        span = self._spans.pop(key, None)
        if span is None:
            return
        span.finish(status=SpanStatus.OK)
        if self._monitor:
            self._monitor.emit(span)

    def _on_span_drop(self, event: Any) -> None:
        key = self._span_key(event)
        span = self._spans.pop(key, None)
        if span is None:
            return
        err = getattr(event, "err", None)
        if err is not None:
            span.finish(status=SpanStatus.ERROR, status_message=str(err))
        else:
            span.finish(status=SpanStatus.OK)
        if self._monitor:
            self._monitor.emit(span)
