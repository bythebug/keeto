"""PII scrubbing utilities for span attributes."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from keeto.core.span import Span

_BUILTIN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    # Credit card: 16 digits with optional spaces/dashes between groups of 4
    (re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"), "[CARD]"),
]


def _scrub_text(text: str, extra: list[re.Pattern[str]]) -> str:
    for pattern, replacement in _BUILTIN:
        text = pattern.sub(replacement, text)
    for pattern in extra:
        text = pattern.sub("[REDACTED]", text)
    return text


def _scrub_value(value: Any, extra: list[re.Pattern[str]]) -> Any:
    if isinstance(value, str):
        return _scrub_text(value, extra)
    if isinstance(value, list):
        return [_scrub_value(item, extra) for item in value]
    if isinstance(value, dict):
        return {k: _scrub_value(v, extra) for k, v in value.items()}
    return value


def scrub_span(span: Span, extra: list[re.Pattern[str]]) -> None:
    """Redact PII from all string attributes in *span* in-place."""
    for key, value in list(span.attributes.items()):
        span.attributes[key] = _scrub_value(value, extra)
