"""
OpenAI plugin for Keeto.

Patches the httpx transport on both sync and async OpenAI clients at
install() time. Extracts token counts, model, cost, streaming data,
tool calls, multimodal inputs, structured output, and batch requests.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from keeto._pricing import cost_usd
from keeto.integrations._httpx import RecordingAsyncTransport, RecordingSyncTransport, _try_parse_json
from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor
    from keeto.core.span import Span

log = logging.getLogger(__name__)

_PROVIDER = "openai"
_CHAT_PATH = "/chat/completions"
_EMBEDDINGS_PATH = "/embeddings"
_BATCHES_PATH = "/batches"


class OpenAIPlugin(Plugin):
    name = "openai"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._patched_clients: list[Any] = []

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        self._patch_openai()

    def uninstall(self) -> None:
        for client, original_transport in self._patched_clients:
            try:
                if hasattr(client, "_transport"):
                    client._transport = original_transport
                elif hasattr(client, "_async_transport"):
                    client._async_transport = original_transport
            except Exception:
                pass
        self._patched_clients.clear()

    def _patch_openai(self) -> None:
        try:
            import openai
        except ImportError:
            return

        plugin = self
        original_init = openai.OpenAI.__init__

        def patched_sync_init(self_client: Any, *args: Any, **kwargs: Any) -> None:
            original_init(self_client, *args, **kwargs)
            plugin._wrap_sync_client(self_client)

        openai.OpenAI.__init__ = patched_sync_init  # type: ignore[method-assign]

        original_async_init = openai.AsyncOpenAI.__init__

        def patched_async_init(self_client: Any, *args: Any, **kwargs: Any) -> None:
            original_async_init(self_client, *args, **kwargs)
            plugin._wrap_async_client(self_client)

        openai.AsyncOpenAI.__init__ = patched_async_init  # type: ignore[method-assign]

    def _wrap_sync_client(self, client: Any) -> None:
        if not hasattr(client, "_transport"):
            return
        original = client._transport
        if isinstance(original, RecordingSyncTransport):
            return
        client._transport = RecordingSyncTransport(
            wrapped=original,
            on_span=self._enrich_span,
            provider=_PROVIDER,
        )
        self._patched_clients.append((client, original))

    def _wrap_async_client(self, client: Any) -> None:
        if not hasattr(client, "_transport"):
            return
        original = client._transport
        if isinstance(original, RecordingAsyncTransport):
            return
        client._transport = RecordingAsyncTransport(
            wrapped=original,
            on_span=self._enrich_span,
            provider=_PROVIDER,
        )
        self._patched_clients.append((client, original))

    def _enrich_span(self, span: Span, request: httpx.Request, response: httpx.Response) -> None:
        path = request.url.path

        if response.status_code == 429:
            self._handle_rate_limit(span, request, response)
        elif _CHAT_PATH in path:
            self._enrich_chat(span, request, response)
        elif _EMBEDDINGS_PATH in path:
            self._enrich_embedding(span, request, response)
        elif _BATCHES_PATH in path:
            self._enrich_batch(span, request, response)

        if self._monitor:
            self._monitor.emit(span)

    def _handle_rate_limit(self, span: Span, request: httpx.Request, response: httpx.Response) -> None:
        span.name = "openai.rate_limit"
        retry_after = response.headers.get("retry-after")
        span.set_attribute("rate_limit.retry_after_s", float(retry_after) if retry_after else None)
        span.set_attribute("http.status_code", 429)

    def _enrich_chat(self, span: Span, request: httpx.Request, response: httpx.Response) -> None:
        span.name = "openai.chat"

        req_body = _try_parse_json(request.content)
        if req_body:
            model = req_body.get("model", "")
            span.model = model
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.stream", req_body.get("stream", False))

            messages = req_body.get("messages", [])
            span.set_attribute("llm.message_count", len(messages))

            # Issue #56: multimodal detection
            has_images = any(
                isinstance(m.get("content"), list)
                and any(c.get("type") == "image_url" for c in m["content"])
                for m in messages
                if isinstance(m, dict)
            )
            if has_images:
                span.set_attribute("llm.multimodal", True)

            # Issue #52: structured output detection
            response_format = req_body.get("response_format")
            if response_format:
                span.set_attribute("llm.response_format", response_format.get("type", "json_object"))

            # Issue #51: tool definitions
            tools = req_body.get("tools") or req_body.get("functions")
            if tools:
                span.set_attribute("llm.tool_count", len(tools))
                span.set_attribute("llm.tool_names", [
                    t.get("function", t).get("name") for t in tools if isinstance(t, dict)
                ])

        resp_body = _try_parse_json(response.content)
        if resp_body and "usage" in resp_body:
            usage = resp_body["usage"]
            span.input_tokens = usage.get("prompt_tokens")
            span.output_tokens = usage.get("completion_tokens")

            details = usage.get("prompt_tokens_details", {})
            span.cached_tokens = details.get("cached_tokens", 0)

            completion_details = usage.get("completion_tokens_details", {})
            span.reasoning_tokens = completion_details.get("reasoning_tokens", 0) or None

            model_name = resp_body.get("model", span.model or "")
            span.model = model_name

            if span.input_tokens is not None and span.output_tokens is not None:
                span.cost_usd = cost_usd(
                    _PROVIDER,
                    model_name,
                    span.input_tokens,
                    span.output_tokens,
                    span.cached_tokens or 0,
                )

        if resp_body:
            choices = resp_body.get("choices", [])
            if choices:
                first = choices[0]
                span.set_attribute("llm.finish_reason", first.get("finish_reason"))

                # Issue #51: tool call capture
                msg = first.get("message", {})
                tool_calls = msg.get("tool_calls") or []
                if tool_calls:
                    span.set_attribute("llm.tool_calls_count", len(tool_calls))
                    span.set_attribute("llm.tool_calls", [
                        {
                            "id": tc.get("id"),
                            "name": tc.get("function", {}).get("name"),
                            "arguments": tc.get("function", {}).get("arguments"),
                        }
                        for tc in tool_calls
                        if isinstance(tc, dict)
                    ])

                # Issue #58: parallel tool calls (multiple tool_calls in one choice)
                if len(tool_calls) > 1:
                    span.set_attribute("llm.parallel_tool_calls", True)

        # Issue #53: retry detection via OpenAI SDK header
        retry_count = request.headers.get("x-stainless-retry-count")
        if retry_count and int(retry_count) > 0:
            span.set_attribute("llm.retry_count", int(retry_count))

        latency = span.attributes.get("http.latency_ms")
        if latency is not None:
            span.set_attribute("llm.latency_ms", latency)

    def _enrich_embedding(self, span: Span, request: httpx.Request, response: httpx.Response) -> None:
        span.name = "openai.embedding"
        span.kind = span.kind.__class__("embedding")  # type: ignore[assignment]
        span.set_attribute("llm.kind", "embedding")

        req_body = _try_parse_json(request.content)
        if req_body:
            model = req_body.get("model", "")
            span.model = model
            span.set_attribute("llm.model", model)

            # Issue #55: batch size
            inp = req_body.get("input")
            if isinstance(inp, list):
                span.set_attribute("llm.embedding_batch_size", len(inp))

            dims = req_body.get("dimensions")
            if dims:
                span.set_attribute("llm.embedding_dimensions", dims)

        resp_body = _try_parse_json(response.content)
        if resp_body:
            usage = resp_body.get("usage", {})
            span.input_tokens = usage.get("prompt_tokens") or usage.get("total_tokens")
            if span.model and span.input_tokens:
                span.cost_usd = cost_usd(_PROVIDER, span.model, span.input_tokens, 0)

            data = resp_body.get("data", [])
            if data and isinstance(data[0], dict):
                span.set_attribute("llm.embedding_dimensions", len(data[0].get("embedding", [])) or None)

    def _enrich_batch(self, span: Span, request: httpx.Request, response: httpx.Response) -> None:
        span.name = "openai.batch"
        span.set_attribute("llm.kind", "batch")

        req_body = _try_parse_json(request.content)
        if req_body:
            span.set_attribute("batch.endpoint", req_body.get("endpoint"))
            span.set_attribute("batch.completion_window", req_body.get("completion_window"))
            model = req_body.get("metadata", {}).get("model")
            if model:
                span.model = model

        resp_body = _try_parse_json(response.content)
        if resp_body:
            span.set_attribute("batch.id", resp_body.get("id"))
            span.set_attribute("batch.status", resp_body.get("status"))
            counts = resp_body.get("request_counts", {})
            if counts:
                span.set_attribute("batch.total_requests", counts.get("total"))
