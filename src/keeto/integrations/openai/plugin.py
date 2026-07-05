"""
OpenAI plugin for Keeto.

Patches the httpx transport on both sync and async OpenAI clients at
install() time. Extracts token counts, model, cost, and streaming data
from OpenAI's JSON response format.
"""

from __future__ import annotations

import json
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

    # ------------------------------------------------------------------
    # Patching
    # ------------------------------------------------------------------

    def _patch_openai(self) -> None:
        try:
            import openai
        except ImportError:
            return

        # Patch the default sync client class so any new OpenAI() instance
        # inherits our transport wrapper.
        original_init = openai.OpenAI.__init__

        plugin = self

        def patched_sync_init(self_client: Any, *args: Any, **kwargs: Any) -> None:
            original_init(self_client, *args, **kwargs)
            plugin._wrap_sync_client(self_client)

        openai.OpenAI.__init__ = patched_sync_init  # type: ignore[method-assign]

        # Async client
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

    # ------------------------------------------------------------------
    # Span enrichment
    # ------------------------------------------------------------------

    def _enrich_span(self, span: Span, request: httpx.Request, response: httpx.Response) -> None:
        path = request.url.path

        if _CHAT_PATH in path:
            self._enrich_chat(span, request, response)
        elif _EMBEDDINGS_PATH in path:
            self._enrich_embedding(span, request, response)

        if self._monitor:
            self._monitor.emit(span)

    def _enrich_chat(self, span: Span, request: httpx.Request, response: httpx.Response) -> None:
        span.name = "openai.chat"

        # Parse request body for model + messages
        req_body = _try_parse_json(request.content)
        if req_body:
            model = req_body.get("model", "")
            span.model = model
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.stream", req_body.get("stream", False))

            messages = req_body.get("messages", [])
            span.set_attribute("llm.message_count", len(messages))

        # Parse response body for usage
        resp_body = _try_parse_json(response.content)
        if resp_body and "usage" in resp_body:
            usage = resp_body["usage"]
            span.input_tokens = usage.get("prompt_tokens")
            span.output_tokens = usage.get("completion_tokens")

            # OpenAI cached token detail lives inside prompt_tokens_details
            details = usage.get("prompt_tokens_details", {})
            span.cached_tokens = details.get("cached_tokens", 0)

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

            finish_reason = None
            choices = resp_body.get("choices", [])
            if choices:
                finish_reason = choices[0].get("finish_reason")
            span.set_attribute("llm.finish_reason", finish_reason)

        latency = span.attributes.get("http.latency_ms")
        if latency is not None:
            span.set_attribute("llm.latency_ms", latency)

    def _enrich_embedding(self, span: Span, request: httpx.Request, response: httpx.Response) -> None:
        span.name = "openai.embedding"
        span.set_attribute("llm.kind", "embedding")

        req_body = _try_parse_json(request.content)
        if req_body:
            span.model = req_body.get("model", "")

        resp_body = _try_parse_json(response.content)
        if resp_body and "usage" in resp_body:
            usage = resp_body["usage"]
            span.input_tokens = usage.get("prompt_tokens")
            if span.model and span.input_tokens:
                span.cost_usd = cost_usd(_PROVIDER, span.model, span.input_tokens, 0)
