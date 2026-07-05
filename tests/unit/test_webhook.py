"""Tests for webhook notifications — issue #86."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from keeto.core.span import Span, SpanKind, SpanStatus, Trace
from keeto.exporters.webhook import WebhookNotifier


def _make_error_span() -> Span:
    now = datetime.now(timezone.utc)
    span = Span(
        trace_id="a" * 32,
        span_id="b" * 16,
        name="openai.chat",
        kind=SpanKind.LLM,
        start_time=now,
        provider="openai",
        model="gpt-4o",
    )
    span.finish(status=SpanStatus.ERROR, status_message="rate limit exceeded")
    return span


class TestWebhookNotifier:
    def test_notify_error_posts_json(self) -> None:
        notifier = WebhookNotifier("http://example.com/hook", on_error=True)
        span = _make_error_span()

        posted: list[dict] = []

        def _fake_post(url: str, content: bytes, headers: dict, timeout: float) -> None:
            posted.append(json.loads(content))

        with patch("keeto.exporters.webhook.httpx") as mock_httpx:
            mock_httpx.post.side_effect = _fake_post
            notifier._send({"type": "error", "span_id": span.span_id, "timestamp": "x"})

        assert len(posted) == 1
        assert posted[0]["type"] == "error"

    def test_on_error_false_skips(self) -> None:
        notifier = WebhookNotifier("http://example.com/hook", on_error=False)
        span = _make_error_span()
        with patch("keeto.exporters.webhook.threading.Thread") as mock_thread:
            notifier.notify_error(span)
            mock_thread.assert_not_called()

    def test_on_budget_false_skips(self) -> None:
        notifier = WebhookNotifier("http://example.com/hook", on_budget=False)
        with patch("keeto.exporters.webhook.threading.Thread") as mock_thread:
            notifier.notify_budget("session", 5.0, 4.0)
            mock_thread.assert_not_called()

    def test_hmac_signature_header(self) -> None:
        secret = "my-secret"
        notifier = WebhookNotifier("http://example.com/hook", secret=secret)

        seen_headers: list[dict] = []

        def _fake_post(url: str, content: bytes, headers: dict, timeout: float) -> None:
            seen_headers.append(headers)

        with patch("keeto.exporters.webhook.httpx") as mock_httpx:
            mock_httpx.post.side_effect = _fake_post
            notifier._send({"type": "test"})

        assert len(seen_headers) == 1
        sig_header = seen_headers[0].get("X-Keeto-Signature", "")
        assert sig_header.startswith("sha256=")
        # Verify the signature is correct
        body = json.dumps({"type": "test"}, default=str).encode()
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert sig_header == f"sha256={expected}"

    def test_budget_payload_fields(self) -> None:
        notifier = WebhookNotifier("http://example.com/hook", on_budget=True)
        posted: list[dict] = []

        with patch("keeto.exporters.webhook.httpx") as mock_httpx:
            mock_httpx.post.side_effect = lambda url, content, headers, timeout: posted.append(
                json.loads(content)
            )
            notifier._send({"type": "budget_exceeded", "budget_kind": "daily", "current": 5.0, "limit": 4.0, "unit": "USD"})

        assert posted[0]["budget_kind"] == "daily"
        assert posted[0]["current"] == 5.0

    def test_send_failure_swallowed(self) -> None:
        notifier = WebhookNotifier("http://example.com/hook")
        with patch("keeto.exporters.webhook.httpx") as mock_httpx:
            mock_httpx.post.side_effect = Exception("connection refused")
            # Should not raise
            notifier._send({"type": "test"})

    def test_fire_async_uses_daemon_thread(self) -> None:
        notifier = WebhookNotifier("http://example.com/hook")
        threads_created: list[threading.Thread] = []

        real_thread = threading.Thread

        def capture_thread(*args: object, **kwargs: object) -> threading.Thread:
            t = real_thread(*args, **kwargs)
            threads_created.append(t)
            return t

        with (
            patch("keeto.exporters.webhook.threading.Thread", side_effect=capture_thread),
            patch("keeto.exporters.webhook.httpx"),
        ):
            notifier._fire_async({"type": "test"})

        assert len(threads_created) == 1
        assert threads_created[0].daemon is True


class TestMonitorWebhookIntegration:
    def test_monitor_set_webhook_wires_notifier(self) -> None:
        from keeto.core.monitor import Monitor

        mon = Monitor(auto=False)
        mon.start()
        mon.set_webhook("http://example.com/hook", on_error=True)
        assert mon._webhook is not None
        mon.stop()

    def test_error_span_fires_webhook(self) -> None:
        from keeto.core.monitor import Monitor

        mon = Monitor(auto=False)
        mon.start()
        mon.set_webhook("http://example.com/hook", on_error=True)

        fired: list[dict] = []
        assert mon._webhook is not None
        mon._webhook.notify_error = lambda span: fired.append({"span_id": span.span_id})  # type: ignore[assignment]

        span = _make_error_span()
        mon.emit(span)
        assert len(fired) == 1

        mon.stop()
