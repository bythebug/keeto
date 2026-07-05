"""
CostView — Cost tab (#26).

Panels:
  1. Session summary  — total spend, request count, avg cost/request
  2. Today vs session — today's spend (midnight-to-now) vs. all-time session
  3. Per-model breakdown — sorted table: model, requests, tokens, cost, % share
  4. Per-provider summary

Refreshed every 2s by KeetoApp's poll loop via refresh_data(traces).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static

from keeto.dashboard.tui.widgets._utils import _fmt_cost, _fmt_tokens

if TYPE_CHECKING:
    from keeto.core.span import Trace
    from keeto.storage.base import StorageBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(part: float, total: float) -> str:
    if total == 0:
        return "—"
    return f"{part / total * 100:.1f}%"


def _midnight_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# CostSummaryBar — three stat chips at the top
# ---------------------------------------------------------------------------

class _StatChip(Static):
    DEFAULT_CSS = """
    _StatChip {
        width: 1fr;
        border: solid $primary-darken-2;
        padding: 0 1;
        margin: 0 1 0 0;
        height: 4;
    }
    """

    def __init__(self, label: str, chip_id: str, value: str = "—") -> None:
        super().__init__()
        self._label = label
        self._chip_id = chip_id
        self._value = value

    def compose(self) -> ComposeResult:
        yield Label(f"[dim]{self._label}[/dim]", markup=True)
        yield Label(f"[bold]{self._value}[/bold]", markup=True, id=self._chip_id)

    def set_value(self, value: str) -> None:
        try:
            self.query_one(f"#{self._chip_id}").update(f"[bold]{value}[/bold]")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CostView
# ---------------------------------------------------------------------------

class CostView(Widget):
    DEFAULT_CSS: ClassVar[str] = """
    CostView {
        layout: vertical;
        height: 1fr;
        padding: 0 1;
    }
    #cost-chips {
        layout: horizontal;
        height: 5;
        margin: 0 0 1 0;
    }
    #section-label {
        color: $text-muted;
        text-style: bold;
        margin: 1 0 0 0;
    }
    #model-table {
        height: 1fr;
    }
    #empty-hint {
        align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    _MODEL_COLS: ClassVar[list[tuple[str, str, int]]] = [
        ("Model",     "model",    22),
        ("Provider",  "provider",  9),
        ("Requests",  "req",       9),
        ("In tok",    "in",        8),
        ("Out tok",   "out",       8),
        ("Cost",      "cost",     10),
        ("Share",     "share",     7),
    ]

    def __init__(self, storage: "StorageBackend") -> None:
        super().__init__()
        self._storage = storage

    def compose(self) -> ComposeResult:
        with Static(id="cost-chips"):
            yield _StatChip("Session cost",  "chip-session", "—")
            yield _StatChip("Today's cost",  "chip-today",   "—")
            yield _StatChip("Avg / request", "chip-avg",     "—")

        yield Label("PER-MODEL BREAKDOWN", id="section-label")
        table: DataTable[str] = DataTable(
            id="model-table", cursor_type="row", zebra_stripes=True
        )
        yield table
        yield Label(
            "[dim]No traces yet — start making AI calls[/dim]",
            id="empty-hint",
            markup=True,
        )

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for label, key, width in self._MODEL_COLS:
            table.add_column(label, key=key, width=width)

    def refresh_data(self, traces: list["Trace"]) -> None:
        """Called every 2s by KeetoApp._poll_storage()."""
        if not traces:
            return

        midnight = _midnight_utc()
        total_cost = 0.0
        today_cost = 0.0
        total_requests = 0

        # Per-model aggregation
        model_stats: dict[str, dict[str, float | int | str]] = defaultdict(
            lambda: {"provider": "", "req": 0, "in": 0, "out": 0, "cost": 0.0}
        )

        for trace in traces:
            tc = trace.total_cost_usd
            total_cost += tc
            total_requests += 1
            if trace.start_time >= midnight:
                today_cost += tc

            key = trace.model or "unknown"
            row = model_stats[key]
            row["provider"] = trace.provider or "—"
            row["req"] = int(row["req"]) + 1
            row["in"] = int(row["in"]) + trace.total_input_tokens
            row["out"] = int(row["out"]) + trace.total_output_tokens
            row["cost"] = float(row["cost"]) + tc

        avg = total_cost / total_requests if total_requests else 0.0

        # Update stat chips
        chips = self.query(_StatChip)
        labels = ["Session cost", "Today's cost", "Avg / request"]
        values = [
            f"[green]{_fmt_cost(total_cost)}[/green]",
            f"[yellow]{_fmt_cost(today_cost)}[/yellow]",
            _fmt_cost(avg),
        ]
        for chip, lbl, val in zip(chips, labels, values):
            chip.set_value(val)

        # Update table
        table = self.query_one(DataTable)
        existing_keys = {str(k.value) for k in table.rows}
        incoming_keys = set(model_stats.keys())

        for key in existing_keys - incoming_keys:
            try:
                table.remove_row(key)
            except Exception:
                pass

        sorted_models = sorted(
            model_stats.items(), key=lambda kv: float(kv[1]["cost"]), reverse=True
        )

        for model, stats in sorted_models:
            row_data = [
                model[:22],
                str(stats["provider"])[:9],
                str(stats["req"]),
                _fmt_tokens(int(stats["in"])),
                _fmt_tokens(int(stats["out"])),
                _fmt_cost(float(stats["cost"])),
                _pct(float(stats["cost"]), total_cost),
            ]
            if model in existing_keys:
                for col_idx, cell in enumerate(row_data):
                    try:
                        table.update_cell(model, self._MODEL_COLS[col_idx][1], cell)
                    except Exception:
                        pass
            else:
                table.add_row(*row_data, key=model)

        # Hide/show empty hint
        hint = self.query_one("#empty-hint")
        hint.display = table.row_count == 0
