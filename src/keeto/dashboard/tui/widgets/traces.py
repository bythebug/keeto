"""
TracesView — left/right split for the Traces tab.

#23  TraceListWidget — scrollable, sortable DataTable
#24  TraceDetailWidget — detail panel (placeholder until #24)
#25  Timeline visualization inside detail panel
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.coordinate import Coordinate
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static

if TYPE_CHECKING:
    from keeto.core.span import Trace
    from keeto.storage.base import StorageBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    delta = datetime.now(timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    return f"{s // 3600}h ago"


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
        for label, key, width, justify in self._COLUMNS:
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
        padding: 0 1;
        overflow-y: auto;
    }
    #detail-placeholder {
        align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, storage: StorageBackend) -> None:
        super().__init__()
        self._storage = storage

    def compose(self) -> ComposeResult:
        with Static(id="list-pane"):
            yield TraceListWidget()
        with Static(id="detail-pane"):
            yield Label(
                "Select a trace to see details",
                id="detail-placeholder",
            )

    def on_trace_list_widget_trace_selected(
        self, event: TraceListWidget.TraceSelected
    ) -> None:
        """Forward to detail panel — TraceDetailWidget wired in issue #24."""
        detail = self.query_one("#detail-pane")
        detail.remove_children()
        # Temporary summary until #24 builds TraceDetailWidget
        lines = [
            f"[bold]Trace[/bold]  {event.trace.trace_id}",
            f"Provider  {event.trace.provider or '—'}",
            f"Model     {event.trace.model or '—'}",
            f"Latency   {_fmt_lat(event.trace.latency_ms)}",
            f"Cost      {_fmt_cost(event.trace.total_cost_usd)}",
            f"Spans     {len(event.trace.spans)}",
            f"Status    {'[red]error[/red]' if event.trace.has_error else '[green]ok[/green]'}",
        ]
        detail.mount(Label("\n".join(lines), markup=True))

    def refresh_data(self, traces: list[Trace]) -> None:
        """Called every 2s by KeetoApp poll loop."""
        self.query_one(TraceListWidget).update(traces)
