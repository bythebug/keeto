"""
Anthropic plugin for Keeto.

Patches httpx transport on both sync and async Anthropic clients.
Extracts model, token counts, and cost from Anthropic's response format.
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

_PROVIDER = "anthropic"
_MESSAGES_PATH = "/v1/messages"


class AnthropicPlugin(Plugin):
    name = "anthropic"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._patched_clients: list[Any] = []

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        self._patch_anthropic()

    def uninstall(self) -> None:
        for client, original_transport in self._patched_clients:
            try:
                client._transport = original_transport
            except Exception:
                pass
        self._patched_clients.clear()

    def _patch_anthropic(self) -> None:
        try:
            import anthropic
        except ImportError:
            return

        plugin = self

        original_init = anthropic.Anthropic.__init__

        def patched_sync_init(self_client: Any, *args: Any, **kwargs: Any) -> None:
            original_init(self_client, *args, **kwargs)
            plugin._wrap_sync_client(self_client)

        anthropic.Anthropic.__init__ = patched_sync_init  # type: ignore[method-assign]

        original_async_init = anthropic.AsyncAnthropic.__init__

        def patched_async_init(self_client: Any, *args: Any, **kwargs: Any) -> None:
            original_async_init(self_client, *args, **kwargs)
            plugin._wrap_async_client(self_client)

        anthropic.AsyncAnthropic.__init__ = patched_async_init  # type: ignore[method-assign]

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
        if _MESSAGES_PATH not in request.url.path:
            return

        span.name = "anthropic.messages"

        req_body = _try_parse_json(request.content)
        if req_body:
            model = req_body.get("model", "")
            span.model = model
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.stream", req_body.get("stream", False))
            messages = req_body.get("messages", [])
            span.set_attribute("llm.message_count", len(messages))
            system = req_body.get("system")
            if system:
                span.set_attribute("llm.has_system_prompt", True)

        resp_body = _try_parse_json(response.content)
        if resp_body:
            model_name = resp_body.get("model", span.model or "")
            span.model = model_name

            usage = resp_body.get("usage", {})
            # Anthropic uses input_tokens / output_tokens directly
            span.input_tokens = usage.get("input_tokens")
            span.output_tokens = usage.get("output_tokens")
            span.cached_tokens = usage.get("cache_read_input_tokens", 0)

            if span.input_tokens is not None and span.output_tokens is not None:
                span.cost_usd = cost_usd(
                    _PROVIDER,
                    model_name,
                    span.input_tokens,
                    span.output_tokens,
                    span.cached_tokens or 0,
                )

            span.set_attribute("llm.stop_reason", resp_body.get("stop_reason"))

        if self._monitor:
            self._monitor.emit(span)
