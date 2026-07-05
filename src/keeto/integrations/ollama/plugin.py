from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, ClassVar

from keeto.core.context import get_current_span_id, get_current_trace_id, new_span_id, new_trace_id
from keeto.core.span import Span, SpanKind, SpanStatus
from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor

_PROVIDER = "ollama"


def _new_span(model: str, name: str) -> Span:
    return Span(
        trace_id=get_current_trace_id() or new_trace_id(),
        span_id=get_current_span_id() or new_span_id(),
        name=name,
        kind=SpanKind.LLM,
        provider=_PROVIDER,
        model=model,
        cost_usd=0.0,
    )


class OllamaPlugin(Plugin):
    name: ClassVar[str] = "ollama"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._originals: dict[str, Any] = {}

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        self._patch_ollama()

    def uninstall(self) -> None:
        try:
            import ollama  # type: ignore[import-untyped]

            for attr, original in self._originals.items():
                setattr(ollama, attr, original)
        except ImportError:
            pass
        self._originals.clear()

    def _patch_ollama(self) -> None:
        try:
            import ollama  # type: ignore[import-untyped]
        except ImportError:
            return

        plugin = self

        for fn_name in ("chat", "generate"):
            original = getattr(ollama, fn_name, None)
            if original is None:
                continue
            self._originals[fn_name] = original

            def _make_sync_wrapper(orig: Any, span_name: str) -> Any:
                def wrapper(*args: Any, **kwargs: Any) -> Any:
                    model = kwargs.get("model") or (args[0] if args else "")
                    span = _new_span(str(model), f"ollama.{span_name}")
                    start = time.perf_counter()
                    try:
                        result = orig(*args, **kwargs)
                        elapsed = (time.perf_counter() - start) * 1000
                        span.set_attribute("llm.latency_ms", elapsed)
                        _enrich_span(span, result)
                        span.finish(status=SpanStatus.OK)
                        plugin._emit(span)
                        return result
                    except Exception as exc:
                        span.set_attribute("llm.latency_ms", (time.perf_counter() - start) * 1000)
                        span.finish(status=SpanStatus.ERROR, status_message=str(exc))
                        plugin._emit(span)
                        raise

                return wrapper

            setattr(ollama, fn_name, _make_sync_wrapper(original, fn_name))

        # Patch AsyncClient methods
        async_client_cls = getattr(ollama, "AsyncClient", None)
        if async_client_cls is not None:
            for fn_name in ("chat", "generate"):
                original_method = getattr(async_client_cls, fn_name, None)
                if original_method is None:
                    continue

                def _make_async_wrapper(orig: Any, span_name: str) -> Any:
                    async def wrapper(self_client: Any, *args: Any, **kwargs: Any) -> Any:
                        model = kwargs.get("model") or (args[0] if args else "")
                        span = _new_span(str(model), f"ollama.{span_name}")
                        start = time.perf_counter()
                        try:
                            result = await orig(self_client, *args, **kwargs)
                            elapsed = (time.perf_counter() - start) * 1000
                            span.set_attribute("llm.latency_ms", elapsed)
                            _enrich_span(span, result)
                            span.finish(status=SpanStatus.OK)
                            plugin._emit(span)
                            return result
                        except Exception as exc:
                            span.set_attribute("llm.latency_ms", (time.perf_counter() - start) * 1000)
                            span.finish(status=SpanStatus.ERROR, status_message=str(exc))
                            plugin._emit(span)
                            raise

                    return wrapper

                setattr(async_client_cls, fn_name, _make_async_wrapper(original_method, fn_name))

    def _emit(self, span: Span) -> None:
        if self._monitor:
            self._monitor.emit(span)


def _enrich_span(span: Span, result: Any) -> None:
    if result is None:
        return
    # ollama returns a dict-like object or Pydantic model
    if hasattr(result, "get"):
        span.input_tokens = result.get("prompt_eval_count")
        span.output_tokens = result.get("eval_count")
    elif hasattr(result, "prompt_eval_count"):
        span.input_tokens = result.prompt_eval_count
        span.output_tokens = getattr(result, "eval_count", None)
