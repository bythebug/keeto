"""
Context propagation for Keeto.

Trace and span IDs are stored in contextvars so they flow automatically
through async calls, coroutines, and threadpool executor tasks without
any user instrumentation.
"""

from __future__ import annotations

import contextvars
import uuid

_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "keeto_trace_id", default=None
)
_span_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "keeto_span_id", default=None
)


def get_current_trace_id() -> str | None:
    return _trace_id_var.get()


def get_current_span_id() -> str | None:
    return _span_id_var.get()


def set_trace_id(trace_id: str) -> contextvars.Token[str | None]:
    return _trace_id_var.set(trace_id)


def set_span_id(span_id: str) -> contextvars.Token[str | None]:
    return _span_id_var.set(span_id)


def reset_trace_id(token: contextvars.Token[str | None]) -> None:
    _trace_id_var.reset(token)


def reset_span_id(token: contextvars.Token[str | None]) -> None:
    _span_id_var.reset(token)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]
