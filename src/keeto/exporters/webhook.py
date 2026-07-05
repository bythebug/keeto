"""Webhook notifications — issue #86.

Fire HTTP POST callbacks when Keeto detects errors or cost/token budget
thresholds are exceeded.

Usage::

    monitor.set_webhook(
        url="https://hooks.slack.com/...",
        on_error=True,
        on_budget=True,
        secret="optional-hmac-sha256-signing-key",
    )
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)


class WebhookNotifier:
    """Fire HTTP webhooks on error spans and budget breaches.

    Calls are made in a background daemon thread so they never block the hot
    path.  Failures are logged at WARNING level and swallowed.
    """

    def __init__(
        self,
        url: str,
        *,
        on_error: bool = True,
        on_budget: bool = True,
        secret: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.url = url
        self.on_error = on_error
        self.on_budget = on_budget
        self._secret = secret.encode() if secret else None
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public trigger API
    # ------------------------------------------------------------------

    def notify_error(self, span: Any) -> None:
        """Fire a webhook for an error span (if on_error is True)."""
        if not self.on_error:
            return
        payload = {
            "type": "error",
            "timestamp": datetime.now(UTC).isoformat(),
            "span_id": span.span_id,
            "trace_id": span.trace_id,
            "name": span.name,
            "provider": span.provider,
            "model": span.model,
            "error_message": span.status_message,
            "latency_ms": span.latency_ms,
        }
        self._fire_async(payload)

    def notify_budget(self, kind: str, current: float, limit: float, unit: str = "USD") -> None:
        """Fire a webhook when a budget threshold is breached."""
        if not self.on_budget:
            return
        payload = {
            "type": "budget_exceeded",
            "timestamp": datetime.now(UTC).isoformat(),
            "budget_kind": kind,
            "current": current,
            "limit": limit,
            "unit": unit,
        }
        self._fire_async(payload)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fire_async(self, payload: dict[str, Any]) -> None:
        t = threading.Thread(target=self._send, args=(payload,), daemon=True)
        t.start()

    def _send(self, payload: dict[str, Any]) -> None:
        try:
            body = json.dumps(payload, default=str).encode()
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self._secret:
                sig = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
                headers["X-Keeto-Signature"] = f"sha256={sig}"
            httpx.post(self.url, content=body, headers=headers, timeout=self._timeout)
        except Exception as exc:
            log.warning("keeto webhook delivery failed: %s", exc)
