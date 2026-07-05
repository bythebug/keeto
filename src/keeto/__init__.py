"""
Keeto — zero-config AI observability for Python.

    from keeto import monitor
    monitor.start()
"""

from keeto._version import __version__
from keeto.core.monitor import Monitor
from keeto.core.span import Span, SpanKind, SpanStatus, Trace

# Global default monitor instance
monitor = Monitor()

__all__ = [
    "Monitor",
    "Span",
    "SpanKind",
    "SpanStatus",
    "Trace",
    "__version__",
    "monitor",
]
