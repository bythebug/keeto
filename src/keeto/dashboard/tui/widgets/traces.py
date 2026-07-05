"""
TracesView — left/right split for the Traces tab.

#23  TraceListWidget — scrollable, sortable DataTable
#24  TraceDetailWidget — full detail panel wired here
#25  Timeline waterfall inside detail panel
#29  SearchBar — filter by model/provider/status/id
#30  Vim-style j/k cursor movement
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label, Static

from keeto.dashboard.tui.widgets._utils import _age, _fmt_cost, _fmt_lat, _fmt_tokens

if TYPE_CHECKING:
    from keeto.core.span import Trace
    from keeto.storage.base import StorageBackend


# ---------------------------------------------------------------------------
# TraceListWidget
# ---------------------------------------------------------------------------

class TraceListWidget(Widget):
    """
    Scrollable, sortable table of captured traces.

    Emits `TraceListWidget.TraceSelected` when the user moves the cursor.
    Refreshes in-place on each poll without losing the cursor position.
    Supports vim-style j/k movement via move_cursor_down / move_cursor_up.
    """

    DEFAULT_CSS: ClassVar[str] = """
    TraceListWidget {
        height: 1fr;
    }
    TraceListWidget DataTable {
        height: 1fr;
    }
    """

    # Columns: (label, key, width, justify)
    _COLUMNS: ClassVar[list[tuple[str, str, int, str]]] = [
        ("ID",       "id",       9,  "left"),
        ("Age",      "age",      8,  "left"),
        ("Provider", "provider", 11, "left"),
        ("Model",    "model",    18, "left"),
        ("Latency",  "latency",  9,  "right"),
        ("In",       "in",       7,  "right"),
        ("Out",      "out",      7,  "right"),
        ("Cost",     "cost",     9,  "right"),
        ("",         "status",   7,  "center"),
    ]

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up",   "Up",   show=False),
        Binding("g", "cursor_top",  "Top",  show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
    ]

    @dataclass
    class TraceSelected(Message):
        trace: "Trace"

    def __init__(self) -> None:
        super().__init__()
        self._traces: list[Trace] = []
        self._trace_map: dict[str, Trace] = {}

    def compose(self) -> ComposeResult:
        table: DataTable[str] = DataTable(cursor_type="row", zebra_stripes=True)
        table.focus()
        yield table

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for label, key, width, _ in self._COLUMNS:
            table.add_column(label, key=key, width=width)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value in self._trace_map:
            self.post_message(
                self.TraceSelected(self._trace_map[event.row_key.value])
            )

    # ------------------------------------------------------------------
    # Vim navigation actions
    # ------------------------------------------------------------------

    def action_cursor_down(self) -> None:
        table = self.query_one(DataTable)
        table.move_cursor(row=min(table.cursor_row + 1, table.row_count - 1))

    def action_cursor_up(self) -> None:
        table = self.query_one(DataTable)
        table.move_cursor(row=max(table.cursor_row - 1, 0))

    def action_cursor_top(self) -> None:
        self.query_one(DataTable).move_cursor(row=0)

    def action_cursor_bottom(self) -> None:
        table = self.query_one(DataTable)
        table.move_cursor(row=max(table.row_count - 1, 0))

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def update(self, traces: list[Trace]) -> None:
        """Refresh the table. Preserves cursor row if trace still exists."""
        table = self.query_one(DataTable)

        # Remember current selection
        current_key: str | None = None
        if table.cursor_row >= 0:
            try:
                current_key = table.get_row_at(table.cursor_row)[0]  # type: ignore[index]
            except Exception:
                pass

        self._traces = traces
        self._trace_map = {t.trace_id: t for t in traces}

        existing_keys = {str(k.value) for k in table.rows}
        incoming_keys = {t.trace_id for t in traces}

        # Remove rows no longer present
        for key in existing_keys - incoming_keys:
            try:
                table.remove_row(key)
            except Exception:
                pass

        # Add or update rows
        for trace in traces:
            row = self._row_cells(trace)
            if trace.trace_id in existing_keys:
                for col_idx, cell in enumerate(row):
                    try:
                        table.update_cell(
                            trace.trace_id,
                            self._COLUMNS[col_idx][1],
                            cell,
                        )
                    except Exception:
                        pass
            else:
                table.add_row(*row, key=trace.trace_id)

        # Restore cursor
        if current_key and current_key in {str(k.value) for k in table.rows}:
            try:
                table.move_cursor(row=table.get_row_index(current_key))
            except Exception:
                pass

    def _row_cells(self, trace: "Trace") -> list[str]:
        status = "[red]✗[/red]" if trace.has_error else "[green]✓[/green]"
        return [
            trace.trace_id[:8],
            _age(trace.start_time),
            trace.provider or "—",
            (trace.model or "—")[:18],
            _fmt_lat(trace.latency_ms),
            _fmt_tokens(trace.total_input_tokens),
            _fmt_tokens(trace.total_output_tokens),
            _fmt_cost(trace.total_cost_usd),
            status,
        ]

    @property
    def selected_trace(self) -> "Trace | None":
        table = self.query_one(DataTable)
        try:
            key = table.get_row_at(table.cursor_row)[0]  # type: ignore[index]
            return self._trace_map.get(str(key))
        except Exception:
            return None


# ---------------------------------------------------------------------------
# TracesView — the full Traces tab (list + search bar + detail panel)
# ---------------------------------------------------------------------------

class TracesView(Widget):
    DEFAULT_CSS: ClassVar[str] = """
    TracesView {
        layout: vertical;
        height: 1fr;
    }
    #search-bar {
        height: 3;
        padding: 0 1;
        border-bottom: solid $primary-darken-2;
    }
    #search-input {
        width: 1fr;
    }
    #match-count {
        width: auto;
        min-width: 12;
        align: right middle;
        color: $text-muted;
        padding: 0 1;
    }
    #main-split {
        layout: horizontal;
        height: 1fr;
    }
    #list-pane {
        width: 2fr;
        border-right: solid $primary-darken-2;
    }
    #detail-pane {
        width: 3fr;
        overflow-y: auto;
    }
    """

    # The current filter text (reactive so CSS / labels react)
    _filter: reactive[str] = reactive("")

    def __init__(self, storage: "StorageBackend") -> None:
        super().__init__()
        self._storage = storage
        self._all_traces: list[Trace] = []

    def compose(self) -> ComposeResult:
        from keeto.dashboard.tui.widgets.detail import TraceDetailWidget  # noqa: PLC0415

        with Static(id="search-bar"):
            yield Input(
                placeholder="Filter by model / provider / status / id  (press / to focus)",
                id="search-input",
            )
            yield Label("", id="match-count")

        with Static(id="main-split"):
            with Static(id="list-pane"):
                yield TraceListWidget()
            with Static(id="detail-pane"):
                yield TraceDetailWidget()

    def on_trace_list_widget_trace_selected(
        self, event: TraceListWidget.TraceSelected
    ) -> None:
        from keeto.dashboard.tui.widgets.detail import TraceDetailWidget  # noqa: PLC0415

        self.query_one(TraceDetailWidget).show(event.trace)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._filter = event.value
            self._apply_filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Return key from search → focus the table
        if event.input.id == "search-input":
            try:
                self.query_one(TraceListWidget).query_one(DataTable).focus()
            except Exception:
                pass

    def focus_search(self) -> None:
        """Called by KeetoApp.action_focus_search to focus the search input."""
        try:
            self.query_one("#search-input", Input).focus()
        except Exception:
            pass

    def refresh_data(self, traces: list["Trace"]) -> None:
        """Called every 2s by KeetoApp poll loop."""
        self._all_traces = traces
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self._filter.lower().strip()
        if q:
            filtered = [
                t for t in self._all_traces
                if q in (t.model or "").lower()
                or q in (t.provider or "").lower()
                or q in t.trace_id.lower()
                or (q in ("error", "err") and t.has_error)
                or (q in ("ok", "success") and not t.has_error)
            ]
        else:
            filtered = self._all_traces

        self.query_one(TraceListWidget).update(filtered)

        count_lbl = self.query_one("#match-count", Label)
        if q:
            count_lbl.update(f"[dim]{len(filtered)}/{len(self._all_traces)}[/dim]")
        else:
            count_lbl.update("")
