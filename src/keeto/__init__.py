"""
Keeto — zero-config AI observability for Python.

    from keeto import monitor
    monitor.start()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from keeto._version import __version__
from keeto.core.monitor import Monitor
from keeto.core.span import Span, SpanKind, SpanStatus, Trace

if TYPE_CHECKING:
    from collections.abc import Callable

# Global default monitor instance
monitor = Monitor()


def trace(name: str, kind: SpanKind | None = None) -> Callable:
    """Decorator that traces a sync or async function using the global monitor.

    Usage::

        from keeto import monitor, trace

        monitor.start()

        @trace("embedding")
        def embed(text: str) -> list[float]:
            ...

        @trace("retrieval")
        async def search(query: str) -> list[str]:
            ...
    """
    return monitor.trace(name, kind=kind)


__all__ = [
    "Monitor",
    "Span",
    "SpanKind",
    "SpanStatus",
    "Trace",
    "__version__",
    "monitor",
    "trace",
]
