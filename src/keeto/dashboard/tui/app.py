"""
Keeto TUI — Textual-based interactive terminal dashboard.

Requires: pip install keeto[tui]

Layout
------
┌─ keeto ──────────────────────────── Live ● 23 req ─┐
│ [Traces] [Cost] [Performance] [Errors]              │
├─────────────────────────────────────────────────────┤
│  (tab content — varies per active tab)              │
├─────────────────────────────────────────────────────┤
│  q quit  /  search  tab  switch  r  refresh         │
└─────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header, TabbedContent, TabPane

from keeto.dashboard.tui.widgets.cost import CostView
from keeto.dashboard.tui.widgets.errors import ErrorsView
from keeto.dashboard.tui.widgets.performance import PerformanceView
from keeto.dashboard.tui.widgets.traces import TracesView

if TYPE_CHECKING:
    from keeto.core.span import Trace
    from keeto.storage.base import StorageBackend

_REFRESH_INTERVAL = 2.0  # seconds between live data polls


class KeetoApp(App[None]):
    """Keeto interactive TUI dashboard."""

    TITLE = "keeto"
    SUB_TITLE = "AI Observability"

    CSS: ClassVar[str] = """
    /* ------------------------------------------------------------------ */
    /* App-level */
    /* ------------------------------------------------------------------ */
    Screen {
        background: $surface;
    }

    Header {
        background: $primary-darken-2;
        color: $text;
        height: 1;
        dock: top;
    }

    Footer {
        background: $primary-darken-3;
        color: $text-muted;
        height: 1;
    }

    /* ------------------------------------------------------------------ */
    /* Tab bar */
    /* ------------------------------------------------------------------ */
    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    /* ------------------------------------------------------------------ */
    /* Live indicator */
    /* ------------------------------------------------------------------ */
    #live-indicator {
        dock: right;
        width: auto;
        padding: 0 1;
        color: $success;
    }

    #live-indicator.stale {
        color: $text-muted;
    }

    /* ------------------------------------------------------------------ */
    /* Placeholder panels (used before each view is wired up) */
    /* ------------------------------------------------------------------ */
    .placeholder {
        align: center middle;
        color: $text-muted;
        height: 1fr;
    }

    /* ------------------------------------------------------------------ */
    /* Traces split layout (implemented in issue #23-#25) */
    /* ------------------------------------------------------------------ */
    #traces-split {
        layout: horizontal;
        height: 1fr;
    }

    #traces-list-pane {
        width: 2fr;
        border-right: solid $primary-darken-2;
    }

    #traces-detail-pane {
        width: 3fr;
        padding: 0 1;
    }

    /* ------------------------------------------------------------------ */
    /* Status bar inside views */
    /* ------------------------------------------------------------------ */
    .status-bar {
        dock: bottom;
        height: 1;
        background: $primary-darken-3;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q",         "quit",           "Quit",       show=True),
        Binding("r",         "refresh",        "Refresh",    show=True),
        Binding("/",         "focus_search",   "Search",     show=True),
        Binding("d",         "toggle_dark",    "Dark/Light", show=True),
        Binding("tab",       "focus_next",     "Next tab",   show=False),
        Binding("shift+tab", "focus_previous", "Prev tab",   show=False),
    ]

    # Reactive trace count shown in the sub-title
    trace_count: reactive[int] = reactive(0)

    def __init__(self, storage: "StorageBackend") -> None:
        super().__init__()
        self._storage = storage

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="traces"):
            with TabPane("Traces", id="traces"):
                yield TracesView(storage=self._storage)
            with TabPane("Cost", id="cost"):
                yield CostView(storage=self._storage)
            with TabPane("Performance", id="performance"):
                yield PerformanceView(storage=self._storage)
            with TabPane("Errors", id="errors"):
                yield ErrorsView(storage=self._storage)
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._schedule_poll)

    def _schedule_poll(self) -> None:
        """Spawn a background worker each tick so storage I/O never blocks the loop."""
        self.run_worker(self._poll_storage(), exclusive=True, name="poll_storage")

    async def _poll_storage(self) -> None:
        traces = await self._storage.list_traces(limit=1000)
        self.trace_count = len(traces)
        self.sub_title = (
            f"Live ● {self.trace_count} trace{'s' if self.trace_count != 1 else ''}"
        )
        self._broadcast_traces(traces)

    def _broadcast_traces(self, traces: list["Trace"]) -> None:
        """Push fresh trace list to every view that knows how to consume it."""
        try:
            self.query_one(TracesView).refresh_data(traces)
        except Exception:
            pass
        try:
            self.query_one(CostView).refresh_data(traces)
        except Exception:
            pass
        try:
            self.query_one(PerformanceView).refresh_data(traces)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        self._schedule_poll()

    def action_focus_search(self) -> None:
        """/ key — focus the search bar in the Traces tab."""
        try:
            self.query_one(TracesView).focus_search()
        except Exception:
            pass

    def action_toggle_dark(self) -> None:
        """d key — toggle between dark and light theme (delegates to Textual built-in)."""
        # Textual ≥0.70 uses theme names; the built-in action handles the toggle
        super().action_toggle_dark()
