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
from datetime import UTC
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from collections.abc import Generator

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
        pii_patterns: list[str] | None = None,
        store_prompts: bool = True,
        auto: bool = True,
    ) -> None:
        import re

        self._storage = storage if storage is not None else MemoryStorage()
        self._pipeline = Pipeline(self._storage)
        self._explicit_plugins: list[Any] = plugins if plugins is not None else []
        self._sample_rate = sample_rate
        self._scrub_pii = scrub_pii
        self._pii_extra: list[re.Pattern[str]] = [re.compile(p) for p in (pii_patterns or [])]
        self._store_prompts = store_prompts
        self._auto = auto
        self._started = False
        self._console = Console(stderr=True)
        self._webhook: Any = None  # WebhookNotifier | None

        # Budget and cost tracking (issues #61, #62)
        self._budget_daily_usd: float | None = None
        self._budget_session_usd: float | None = None
        self._session_cost_usd: float = 0.0
        self._daily_cost_usd: float = 0.0
        self._daily_cost_date: Any = None  # datetime.date
        self._cost_by_provider: dict[str, float] = {}
        self._cost_by_model: dict[str, float] = {}
        self._budget_alert_fired: set[str] = set()

        # Token budget tracking (#76)
        self._token_budget_monthly: int | None = None
        self._token_budget_daily: int | None = None
        self._session_tokens: int = 0
        self._daily_tokens: int = 0
        self._daily_tokens_date: Any = None  # datetime.date

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
                with contextlib.suppress(Exception):
                    plugin.uninstall()

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
        # Sampling: errors are always captured regardless of sample_rate.
        if self._sample_rate < 1.0 and span.status != SpanStatus.ERROR:
            import random
            if random.random() > self._sample_rate:
                return
        if self._scrub_pii:
            from keeto.core._pii import scrub_span
            scrub_span(span, self._pii_extra)
        self._pipeline.emit(span)
        if span.cost_usd is not None:
            self._session_cost_usd += span.cost_usd
            self._accumulate_cost(span)
            self._check_budget()
        self._accumulate_tokens(span)
        if self._webhook and span.status == SpanStatus.ERROR:
            self._webhook.notify_error(span)

    # ------------------------------------------------------------------
    # Budget management (issue #61)
    # ------------------------------------------------------------------

    def set_budget(
        self,
        daily_usd: float | None = None,
        session_usd: float | None = None,
    ) -> None:
        """Set cost budget thresholds. Logs a warning when exceeded."""
        self._budget_daily_usd = daily_usd
        self._budget_session_usd = session_usd

    def _accumulate_cost(self, span: Span) -> None:
        from datetime import date

        cost = span.cost_usd
        if cost is None:
            return

        today = date.today()
        if self._daily_cost_date != today:
            self._daily_cost_date = today
            self._daily_cost_usd = 0.0
        self._daily_cost_usd += cost

        p = span.provider or "unknown"
        m = span.model or "unknown"
        self._cost_by_provider[p] = self._cost_by_provider.get(p, 0.0) + cost
        self._cost_by_model[m] = self._cost_by_model.get(m, 0.0) + cost

    def _check_budget(self) -> None:
        from datetime import date

        if self._budget_session_usd is not None:
            key = "session"
            if key not in self._budget_alert_fired and self._session_cost_usd >= self._budget_session_usd:
                self._budget_alert_fired.add(key)
                self._console.print(
                    f"[yellow]keeto: session budget exceeded "
                    f"(${self._session_cost_usd:.4f} >= ${self._budget_session_usd:.4f})[/yellow]"
                )
                if self._webhook:
                    self._webhook.notify_budget("session", self._session_cost_usd, self._budget_session_usd)

        if self._budget_daily_usd is not None:
            key = f"daily_{date.today()}"
            if key not in self._budget_alert_fired and self._daily_cost_usd >= self._budget_daily_usd:
                self._budget_alert_fired.add(key)
                self._console.print(
                    f"[yellow]keeto: daily budget exceeded "
                    f"(${self._daily_cost_usd:.4f} >= ${self._budget_daily_usd:.4f})[/yellow]"
                )
                if self._webhook:
                    self._webhook.notify_budget("daily", self._daily_cost_usd, self._budget_daily_usd)

    # ------------------------------------------------------------------
    # Token budget tracking (issue #76)
    # ------------------------------------------------------------------

    def set_token_budget(
        self,
        monthly: int | None = None,
        daily: int | None = None,
    ) -> None:
        """Set token budget thresholds. Logs a warning when exceeded."""
        self._token_budget_monthly = monthly
        self._token_budget_daily = daily

    def _accumulate_tokens(self, span: Span) -> None:
        from datetime import date

        total = (span.input_tokens or 0) + (span.output_tokens or 0)
        if total == 0:
            return

        self._session_tokens += total

        today = date.today()
        if self._daily_tokens_date != today:
            self._daily_tokens_date = today
            self._daily_tokens = 0
        self._daily_tokens += total

        self._check_token_budget()

    def _check_token_budget(self) -> None:
        from datetime import date

        if self._token_budget_daily is not None:
            key = f"token_daily_{date.today()}"
            if key not in self._budget_alert_fired and self._daily_tokens >= self._token_budget_daily:
                self._budget_alert_fired.add(key)
                self._console.print(
                    f"[yellow]keeto: daily token budget exceeded "
                    f"({self._daily_tokens:,} >= {self._token_budget_daily:,} tokens)[/yellow]"
                )

        if self._token_budget_monthly is not None:
            from datetime import date as _date

            key = f"token_monthly_{_date.today().year}_{_date.today().month}"
            if key not in self._budget_alert_fired and self._session_tokens >= self._token_budget_monthly:
                self._budget_alert_fired.add(key)
                self._console.print(
                    f"[yellow]keeto: monthly token budget exceeded "
                    f"({self._session_tokens:,} >= {self._token_budget_monthly:,} tokens)[/yellow]"
                )

    def token_summary(self) -> dict[str, Any]:
        """Return token usage summary for the current session."""
        return {
            "session_tokens": self._session_tokens,
            "today_tokens": self._daily_tokens,
            "budget_daily": self._token_budget_daily,
            "budget_monthly": self._token_budget_monthly,
        }

    # ------------------------------------------------------------------
    # Cost aggregation (issue #62)
    # ------------------------------------------------------------------

    def cost_summary(self) -> dict[str, Any]:
        """Return a cost summary dict with session, today, and per-provider totals."""
        return {
            "session_usd": round(self._session_cost_usd, 6),
            "today_usd": round(self._daily_cost_usd, 6),
            "by_provider": {k: round(v, 6) for k, v in sorted(self._cost_by_provider.items(), key=lambda x: -x[1])},
            "by_model": {k: round(v, 6) for k, v in sorted(self._cost_by_model.items(), key=lambda x: -x[1])},
        }

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
            self._console.print("[red]TUI dashboard requires textual. Install with: pip install keeto[tui][/red]")
            return
        KeetoApp(storage=self._storage).run()

    def _dashboard_web(self) -> None:
        try:
            from keeto.dashboard.web.server import start_web_dashboard
        except ImportError:
            self._console.print("[red]Web dashboard requires fastapi. Install with: pip install keeto[web][/red]")
            return
        start_web_dashboard(self._storage, block=False)

    # ------------------------------------------------------------------
    # Webhook (issue #86)
    # ------------------------------------------------------------------

    def set_webhook(
        self,
        url: str,
        *,
        on_error: bool = True,
        on_budget: bool = True,
        secret: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        """Configure a webhook URL for error and budget notifications.

        :param url: HTTP endpoint to POST to.
        :param on_error: Fire when an error span is emitted.
        :param on_budget: Fire when a cost/token budget is exceeded.
        :param secret: Optional HMAC-SHA256 signing key for ``X-Keeto-Signature`` header.
        :param timeout: Request timeout in seconds (default 5 s).
        """
        from keeto.exporters.webhook import WebhookNotifier

        self._webhook: WebhookNotifier | None = WebhookNotifier(
            url,
            on_error=on_error,
            on_budget=on_budget,
            secret=secret,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(
        self,
        path: str | None = None,
        format: str | None = None,
        since: Any | None = None,
        until: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Export captured traces.

        :param path: Output file path (format inferred from extension).
        :param format: Explicit format: ``"json"``, ``"csv"``, ``"otel"``,
            ``"langsmith"``, or ``"mlflow"``.
        :param since: Only export traces with start_time >= this value
            (``datetime`` or ISO-8601 string).
        :param until: Only export traces with start_time <= this value.

        Examples::

            monitor.export("traces.json")
            monitor.export("traces.csv")
            monitor.export(format="otel", endpoint="http://jaeger:4317")
            monitor.export(format="langsmith", project_name="my-project")
            monitor.export(format="mlflow", experiment_name="my-exp")
            monitor.export("traces.json", since="2024-01-01", until="2024-01-31")
        """
        import asyncio
        from datetime import datetime

        def _parse_dt(v: Any) -> datetime | None:
            if v is None:
                return None
            if isinstance(v, datetime):
                return v if v.tzinfo else v.replace(tzinfo=UTC)
            dt = datetime.fromisoformat(str(v))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        since_dt = _parse_dt(since)
        until_dt = _parse_dt(until)

        traces = asyncio.run(self._storage.list_traces(limit=10_000, since=since_dt, until=until_dt))

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
        elif format == "langsmith":
            from keeto.exporters.langsmith import export_langsmith

            export_langsmith(traces, path=path, **kwargs)
        elif format == "mlflow":
            from keeto.exporters.mlflow import export_mlflow

            export_mlflow(traces, **kwargs)
        else:
            raise ValueError(f"Unknown export format: {format!r}. Use 'json', 'csv', 'otel', 'langsmith', or 'mlflow'.")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def recommendations(self) -> Any:
        """Return a RecommendationsReport with rule-based findings."""
        import asyncio

        from keeto.analyzers.recommendations import RecommendationsEngine

        traces = asyncio.run(self._storage.list_traces(limit=10_000))
        engine = RecommendationsEngine()
        return engine.analyze(traces)

    def compare(self, trace_a: Trace, trace_b: Trace) -> Any:
        """Side-by-side comparison of two traces. Returns a TraceComparison."""
        from keeto.analyzers.comparison import TraceComparison

        return TraceComparison.from_traces(trace_a, trace_b)

    # ------------------------------------------------------------------
    # LangSmith import (issue #89)
    # ------------------------------------------------------------------

    def import_langsmith(
        self,
        project_name: str,
        limit: int = 100,
        api_key: str | None = None,
        api_url: str | None = None,
    ) -> int:
        """Import runs from a LangSmith project into the current storage.

        Returns the number of traces imported.  Requires the ``langsmith``
        package and a valid ``LANGCHAIN_API_KEY`` env var (or pass *api_key*).

        Example::

            count = monitor.import_langsmith("my-project", limit=50)
            monitor.compare(monitor.traces[0], monitor.traces[1])
        """
        import asyncio

        from keeto.exporters.langsmith import import_from_langsmith

        traces = import_from_langsmith(project_name, limit=limit, api_key=api_key, api_url=api_url)
        for trace in traces:
            for span in trace.spans:
                asyncio.run(self._storage.append(span))
        return len(traces)


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
