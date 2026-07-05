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
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, Static, TabbedContent, TabPane

from keeto.dashboard.tui.widgets.cost import CostView
from keeto.dashboard.tui.widgets.errors import ErrorsView
from keeto.dashboard.tui.widgets.performance import PerformanceView
from keeto.dashboard.tui.widgets.traces import TracesView

if TYPE_CHECKING:
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
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("/", "focus_search", "Search", show=True),
        Binding("tab", "focus_next", "Next tab", show=False),
        Binding("shift+tab", "focus_previous", "Prev tab", show=False),
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
    ]

    # Reactive trace count shown in the live indicator
    trace_count: reactive[int] = reactive(0)

    def __init__(self, storage: StorageBackend) -> None:
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
        self.set_interval(_REFRESH_INTERVAL, self._poll_storage)

    async def _poll_storage(self) -> None:
        traces = await self._storage.list_traces(limit=1000)
        self.trace_count = len(traces)
        self.sub_title = f"Live ● {self.trace_count} trace{'s' if self.trace_count != 1 else ''}"
        # Notify views to refresh
        self.query_one(TracesView).refresh_data(traces)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        self.run_worker(self._poll_storage())

    def action_focus_search(self) -> None:
        # Will wire to TracesView search box in issue #29
        pass

    def action_scroll_down(self) -> None:
        self.screen.scroll_down()

    def action_scroll_up(self) -> None:
        self.screen.scroll_up()
