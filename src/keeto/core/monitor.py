"""
Monitor — the single user-facing entry point for Keeto.

    from keeto import monitor
    monitor.start()

    # or with explicit config
    monitor = Monitor(storage=SQLiteStorage("./keeto.db"), sample_rate=0.1)
    monitor.start()
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Generator
from typing import Any

from rich.console import Console

from keeto.core.context import (
    new_span_id,
    new_trace_id,
    reset_span_id,
    reset_trace_id,
    set_span_id,
    set_trace_id,
)
from keeto.core.pipeline import Pipeline
from keeto.core.span import Span, SpanKind, SpanStatus, Trace
from keeto.storage.memory import MemoryStorage

log = logging.getLogger(__name__)


class _SpanContext:
    """Holder object yielded by monitor.span(). Lifecycle is managed by the generator."""

    def __init__(self, span: Span) -> None:
        self._span = span

    @property
    def span(self) -> Span:
        return self._span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, value)


class Monitor:
    """
    Central coordinator for Keeto observability.

    One global default instance is created at import time and accessible via
    `from keeto import monitor`. Create additional instances for isolated
    monitoring contexts.
    """

    def __init__(
        self,
        storage: Any | None = None,
        plugins: list[Any] | None = None,
        sample_rate: float = 1.0,
        scrub_pii: bool = False,
        store_prompts: bool = True,
        auto: bool = True,
    ) -> None:
        self._storage = storage or MemoryStorage()
        self._pipeline = Pipeline(self._storage)
        self._explicit_plugins: list[Any] = plugins or []
        self._sample_rate = sample_rate
        self._scrub_pii = scrub_pii
        self._store_prompts = store_prompts
        self._auto = auto
        self._started = False
        self._console = Console(stderr=True)

        # Lazy-imported to avoid circular imports
        self._registry: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._pipeline.start()
        self._started = True

        from keeto.plugins.registry import PluginRegistry

        self._registry = PluginRegistry()

        # Install explicitly provided plugins first
        for plugin in self._explicit_plugins:
            plugin.install(self)
            self._registry.register(plugin)

        # Auto-discover remaining plugins
        if self._auto and not self._explicit_plugins:
            loaded = self._registry.auto_discover(self)
            if loaded:
                names = ", ".join(p.name for p in loaded)
                self._console.print(f"[dim]keeto: loaded plugins → {names}[/dim]")

    def stop(self) -> None:
        if not self._started:
            return
        self._pipeline.stop()
        self._started = False
        if self._registry:
            for plugin in self._registry.all():
                try:
                    plugin.uninstall()
                except Exception:
                    pass

    def use(self, plugin: Any) -> Monitor:
        """Fluent plugin registration. Can be called before or after start()."""
        self._explicit_plugins.append(plugin)
        if self._started and self._registry:
            plugin.install(self)
            self._registry.register(plugin)
        return self

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> Monitor:
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Span creation
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def span(
        self,
        name: str,
        kind: SpanKind = SpanKind.CUSTOM,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> Generator[_SpanContext, None, None]:
        """Create and manage a span as a context manager."""
        from keeto.core.context import get_current_span_id, get_current_trace_id

        tid = trace_id or get_current_trace_id() or new_trace_id()
        sid = new_span_id()
        psid = parent_span_id or get_current_span_id()

        sp = Span(trace_id=tid, span_id=sid, parent_span_id=psid, name=name, kind=kind)
        ctx = _SpanContext(sp)

        trace_token = set_trace_id(tid)
        span_token = set_span_id(sid)

        try:
            yield ctx
            sp.finish(status=SpanStatus.OK)
        except Exception as exc:
            sp.finish(status=SpanStatus.ERROR, status_message=str(exc))
            raise
        finally:
            self._pipeline.emit(sp)
            reset_trace_id(trace_token)
            reset_span_id(span_token)

    # ------------------------------------------------------------------
    # Direct span emission (used by plugins)
    # ------------------------------------------------------------------

    def emit(self, span: Span) -> None:
        """Emit a completed span directly (called by plugin interceptors)."""
        if not self._started:
            return
        self._pipeline.emit(span)

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def traces(self) -> _TracesProxy:
        return _TracesProxy(self._storage)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def dashboard(self, mode: str = "rich") -> None:
        """
        Launch the Keeto dashboard.

        mode="rich"  — Rich table summary in the terminal (no extra deps)
        mode="tui"   — Interactive Textual TUI  [requires: keeto[tui]]
        mode="web"   — Browser dashboard         [requires: keeto[web]]
        """
        if mode == "rich":
            self._dashboard_rich()
        elif mode == "tui":
            self._dashboard_tui()
        elif mode == "web":
            self._dashboard_web()
        else:
            raise ValueError(f"Unknown dashboard mode: {mode!r}. Use 'rich', 'tui', or 'web'.")

    def _dashboard_rich(self) -> None:
        import asyncio

        from keeto.dashboard.rich_summary import render

        traces = asyncio.run(self._storage.list_traces(limit=200))
        render(traces, console=self._console)

    def _dashboard_tui(self) -> None:
        try:
            from keeto.dashboard.tui.app import KeetoApp
        except ImportError:
            self._console.print(
                "[red]TUI dashboard requires textual. Install with: pip install keeto[tui][/red]"
            )
            return
        KeetoApp(storage=self._storage).run()

    def _dashboard_web(self) -> None:
        try:
            from keeto.dashboard.web.server import start_web_dashboard
        except ImportError:
            self._console.print(
                "[red]Web dashboard requires fastapi. Install with: pip install keeto[web][/red]"
            )
            return
        start_web_dashboard(self._storage, block=False)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(
        self, path: str | None = None, format: str | None = None, **kwargs: Any
    ) -> None:
        """
        Export captured traces.

        monitor.export("traces.json")         # inferred from extension
        monitor.export("traces.csv")
        monitor.export(format="otel", endpoint="http://jaeger:4317")
        """
        import asyncio

        traces = asyncio.run(self._storage.list_traces(limit=10_000))

        if format is None and path:
            ext = path.rsplit(".", 1)[-1].lower()
            format = ext

        if format == "json":
            from keeto.exporters.json import export_json
            export_json(traces, path)
        elif format == "csv":
            from keeto.exporters.csv import export_csv
            export_csv(traces, path)
        elif format == "otel":
            from keeto.exporters.otel import export_otel
            export_otel(traces, **kwargs)
        else:
            raise ValueError(f"Unknown export format: {format!r}. Use 'json', 'csv', or 'otel'.")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def recommendations(self) -> Any:
        from keeto.analyzers.recommendations import RecommendationsEngine
        import asyncio

        traces = asyncio.run(self._storage.list_traces(limit=10_000))
        engine = RecommendationsEngine()
        return engine.analyze(traces)


class _TracesProxy:
    """Synchronous proxy for async storage list operations."""

    def __init__(self, storage: Any) -> None:
        self._storage = storage

    def __getitem__(self, index: int) -> Trace:
        import asyncio
        traces = asyncio.run(self._storage.list_traces(limit=1000))
        return traces[index]

    def __len__(self) -> int:
        import asyncio
        return len(asyncio.run(self._storage.list_traces(limit=10_000)))

    def __iter__(self):  # type: ignore[override]
        import asyncio
        return iter(asyncio.run(self._storage.list_traces(limit=10_000)))
