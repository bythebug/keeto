"""
TracesView — left/right split for the Traces tab.

#23  TraceListWidget — scrollable, sortable DataTable
#24  TraceDetailWidget — full detail panel wired here
#25  Timeline waterfall inside detail panel
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

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
# TracesView — the full Traces tab
# ---------------------------------------------------------------------------

class TracesView(Widget):
    DEFAULT_CSS: ClassVar[str] = """
    TracesView {
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

    def __init__(self, storage: "StorageBackend") -> None:
        super().__init__()
        self._storage = storage

    def compose(self) -> ComposeResult:
        # Import here to break the potential circular-import at module load time;
        # detail.py imports from _utils, NOT from this file.
        from keeto.dashboard.tui.widgets.detail import TraceDetailWidget  # noqa: PLC0415

        with Static(id="list-pane"):
            yield TraceListWidget()
        with Static(id="detail-pane"):
            yield TraceDetailWidget()

    def on_trace_list_widget_trace_selected(
        self, event: TraceListWidget.TraceSelected
    ) -> None:
        from keeto.dashboard.tui.widgets.detail import TraceDetailWidget  # noqa: PLC0415

        self.query_one(TraceDetailWidget).show(event.trace)

    def refresh_data(self, traces: list["Trace"]) -> None:
        """Called every 2s by KeetoApp poll loop."""
        self.query_one(TraceListWidget).update(traces)
