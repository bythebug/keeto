"""Shared formatting helpers for TUI widgets."""

from __future__ import annotations

from datetime import UTC, datetime


def _fmt_lat(ms: float | None) -> str:
    if ms is None:
        return "—"
    return f"{ms / 1000:.2f}s" if ms >= 1000 else f"{ms:.0f}ms"


def _fmt_tokens(n: int) -> str:
    if n == 0:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _fmt_cost(usd: float) -> str:
    if usd == 0:
        return "—"
    return f"${usd:.4f}" if usd >= 0.0001 else f"${usd:.6f}"


def _age(dt: datetime) -> str:
    delta = datetime.now(UTC) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    return f"{s // 3600}h ago"
