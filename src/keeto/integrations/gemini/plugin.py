from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, ClassVar

from keeto.core.context import get_current_span_id, get_current_trace_id, new_span_id, new_trace_id
from keeto.core.span import Span, SpanKind, SpanStatus
from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor

_PROVIDER = "google"


def _new_span(model: str) -> Span:
    return Span(
        trace_id=get_current_trace_id() or new_trace_id(),
        span_id=get_current_span_id() or new_span_id(),
        name="gemini.generate",
        kind=SpanKind.LLM,
        provider=_PROVIDER,
        model=model,
    )


class GeminiPlugin(Plugin):
    name: ClassVar[str] = "gemini"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._original_generate: Any = None
        self._original_generate_async: Any = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        self._patch_gemini()

    def uninstall(self) -> None:
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]

            if self._original_generate is not None:
                genai.GenerativeModel.generate_content = self._original_generate
            if self._original_generate_async is not None:
                genai.GenerativeModel.generate_content_async = self._original_generate_async
        except ImportError:
            pass
        self._original_generate = None
        self._original_generate_async = None

    def _patch_gemini(self) -> None:
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
        except ImportError:
            return

        plugin = self
        self._original_generate = genai.GenerativeModel.generate_content
        self._original_generate_async = getattr(genai.GenerativeModel, "generate_content_async", None)

        original_sync = self._original_generate

        def patched_generate(self_model: Any, *args: Any, **kwargs: Any) -> Any:
            model_name: str = getattr(self_model, "model_name", "") or ""
            span = _new_span(model_name)
            start = time.perf_counter()
            try:
                result = original_sync(self_model, *args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                span.set_attribute("llm.latency_ms", elapsed)
                _enrich_from_result(span, result, model_name)
                span.finish(status=SpanStatus.OK)
                plugin._emit(span)
                return result
            except Exception as exc:
                span.set_attribute("llm.latency_ms", (time.perf_counter() - start) * 1000)
                span.finish(status=SpanStatus.ERROR, status_message=str(exc))
                plugin._emit(span)
                raise

        genai.GenerativeModel.generate_content = patched_generate  # type: ignore[method-assign]

        if self._original_generate_async is not None:
            original_async = self._original_generate_async

            async def patched_generate_async(self_model: Any, *args: Any, **kwargs: Any) -> Any:
                model_name2: str = getattr(self_model, "model_name", "") or ""
                span = _new_span(model_name2)
                start = time.perf_counter()
                try:
                    result = await original_async(self_model, *args, **kwargs)
                    elapsed = (time.perf_counter() - start) * 1000
                    span.set_attribute("llm.latency_ms", elapsed)
                    _enrich_from_result(span, result, model_name2)
                    span.finish(status=SpanStatus.OK)
                    plugin._emit(span)
                    return result
                except Exception as exc:
                    span.set_attribute("llm.latency_ms", (time.perf_counter() - start) * 1000)
                    span.finish(status=SpanStatus.ERROR, status_message=str(exc))
                    plugin._emit(span)
                    raise

            genai.GenerativeModel.generate_content_async = patched_generate_async  # type: ignore[method-assign]

    def _emit(self, span: Span) -> None:
        if self._monitor:
            self._monitor.emit(span)


def _enrich_from_result(span: Span, result: Any, model_name: str) -> None:
    from keeto._pricing import cost_usd

    usage = getattr(result, "usage_metadata", None)
    if usage is not None:
        input_tok = getattr(usage, "prompt_token_count", None)
        output_tok = getattr(usage, "candidates_token_count", None)
        span.input_tokens = input_tok
        span.output_tokens = output_tok
        if input_tok is not None and output_tok is not None:
            span.cost_usd = cost_usd(_PROVIDER, model_name, input_tok, output_tok)
