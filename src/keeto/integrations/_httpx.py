"""
Base httpx transport wrapper shared by all httpx-based SDK plugins.

Strategy: wrap the SDK client's httpx transport so every HTTP request/response
is intercepted without the user changing any code. For async clients we wrap
AsyncHTTPTransport; for sync clients we wrap HTTPTransport.

Plugins subclass HttpxInterceptor and override parse_request / parse_response
to extract SDK-specific semantic data (model name, token counts, etc.).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from keeto.core.context import (
    get_current_span_id,
    get_current_trace_id,
    new_span_id,
    new_trace_id,
)
from keeto.core.span import Span, SpanKind, SpanStatus


class RecordingAsyncTransport(httpx.AsyncBaseTransport):
    """
    Wraps an existing async transport and emits a Span for each request.
    The emit callback is provided by the plugin so it can enrich spans
    before forwarding to the Monitor pipeline.
    """

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport,
        on_span: Any,  # Callable[[Span], None]
        provider: str,
    ) -> None:
        self._wrapped = wrapped
        self._on_span = on_span
        self._provider = provider

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        trace_id = get_current_trace_id() or new_trace_id()
        span_id = get_current_span_id() or new_span_id()

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            name=f"{self._provider}.request",
            kind=SpanKind.LLM,
            provider=self._provider,
        )
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", str(request.url))

        start = time.perf_counter()
        error: Exception | None = None
        response: httpx.Response | None = None

        try:
            response = await self._wrapped.handle_async_request(request)
            return response
        except Exception as exc:
            error = exc
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("http.latency_ms", elapsed_ms)

            if error is not None:
                span.finish(
                    status=SpanStatus.ERROR,
                    status_message=str(error),
                )
            elif response is not None:
                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 400:
                    span.finish(status=SpanStatus.ERROR)
                else:
                    span.finish(status=SpanStatus.OK)
                # Let the plugin enrich from the response body
                try:
                    self._on_span(span, request, response)
                except Exception:
                    pass
            else:
                span.finish(status=SpanStatus.UNSET)


class RecordingSyncTransport(httpx.BaseTransport):
    """Sync counterpart of RecordingAsyncTransport."""

    def __init__(
        self,
        wrapped: httpx.BaseTransport,
        on_span: Any,
        provider: str,
    ) -> None:
        self._wrapped = wrapped
        self._on_span = on_span
        self._provider = provider

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        trace_id = get_current_trace_id() or new_trace_id()
        span_id = get_current_span_id() or new_span_id()

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            name=f"{self._provider}.request",
            kind=SpanKind.LLM,
            provider=self._provider,
        )
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", str(request.url))

        start = time.perf_counter()
        error: Exception | None = None
        response: httpx.Response | None = None

        try:
            response = self._wrapped.handle_request(request)
            return response
        except Exception as exc:
            error = exc
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("http.latency_ms", elapsed_ms)

            if error is not None:
                span.finish(status=SpanStatus.ERROR, status_message=str(error))
            elif response is not None:
                span.set_attribute("http.status_code", response.status_code)
                status = SpanStatus.ERROR if response.status_code >= 400 else SpanStatus.OK
                span.finish(status=status)
                try:
                    self._on_span(span, request, response)
                except Exception:
                    pass
            else:
                span.finish(status=SpanStatus.UNSET)


def _try_parse_json(content: bytes) -> dict[str, Any] | None:
    try:
        return json.loads(content)  # type: ignore[no-any-return]
    except Exception:
        return None
