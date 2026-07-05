"""
PerformanceView — Performance tab (#27).

Panels:
  1. Latency stat chips  — P50, P95, P99, mean
  2. ASCII histogram     — latency bucket bars
  3. Per-model table     — model, requests, min, p50, p95, p99
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, ClassVar

from textual.widget import Widget
from textual.widgets import DataTable, Label, Static

from keeto.dashboard.tui.widgets._utils import _fmt_lat

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from keeto.core.span import Trace
    from keeto.storage.base import StorageBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HIST_BAR = "█"
_HIST_HALF = "▌"

# Bucket edges in ms
_BUCKETS: list[tuple[float, float, str]] = [
    (0, 100, "<100ms"),
    (100, 250, "100-250ms"),
    (250, 500, "250-500ms"),
    (500, 1000, "500ms-1s"),
    (1000, 2000, "1-2s"),
    (2000, 5000, "2-5s"),
    (5000, float("inf"), ">5s"),
]


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    idx = (len(sorted_vals) - 1) * p / 100
    lo = int(idx)
    hi = lo + 1
    frac = idx - lo
    if hi >= len(sorted_vals):
        return sorted_vals[lo]
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _build_histogram(latencies: list[float], bar_cols: int = 28) -> str:
    """Return a multi-line ASCII histogram string."""
    counts = [0] * len(_BUCKETS)
    for ms in latencies:
        for i, (lo, hi, _) in enumerate(_BUCKETS):
            if lo <= ms < hi:
                counts[i] += 1
                break

    max_count = max(counts, default=0)
    if max_count == 0:
        return "(no data)"

    lines: list[str] = []
    for (_, _, label), count in zip(_BUCKETS, counts, strict=False):
        filled = round(count / max_count * bar_cols)
        bar = _HIST_BAR * filled
        pct = f"{count / len(latencies) * 100:4.1f}%"
        lines.append(f"  {label:>10}  [cyan]{bar:<{bar_cols}}[/cyan]  {pct:>6}  ({count})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stat chip (reuse the same pattern as CostView)
# ---------------------------------------------------------------------------


class _PerfChip(Static):
    DEFAULT_CSS = """
    _PerfChip {
        width: 1fr;
        border: solid $primary-darken-2;
        padding: 0 1;
        margin: 0 1 0 0;
        height: 4;
    }
    """

    def __init__(self, label: str, chip_id: str) -> None:
        super().__init__()
        self._label = label
        self._chip_id = chip_id

    def compose(self) -> ComposeResult:
        yield Label(f"[dim]{self._label}[/dim]", markup=True)
        yield Label("[bold]—[/bold]", markup=True, id=self._chip_id)

    def set_value(self, value: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one(f"#{self._chip_id}").update(f"[bold]{value}[/bold]")


# ---------------------------------------------------------------------------
# PerformanceView
# ---------------------------------------------------------------------------


class PerformanceView(Widget):
    DEFAULT_CSS: ClassVar[str] = """
    PerformanceView {
        layout: vertical;
        height: 1fr;
        padding: 0 1;
    }
    #perf-chips {
        layout: horizontal;
        height: 5;
        margin: 0 0 1 0;
    }
    #hist-label {
        color: $text-muted;
        text-style: bold;
        margin: 1 0 0 0;
    }
    #histogram {
        height: 9;
        margin: 0 0 1 0;
        padding: 0 1;
        border: solid $primary-darken-2;
        color: $text;
    }
    #model-label {
        color: $text-muted;
        text-style: bold;
        margin: 1 0 0 0;
    }
    #perf-table {
        height: 1fr;
    }
    #empty-hint {
        align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    _MODEL_COLS: ClassVar[list[tuple[str, str, int]]] = [
        ("Model", "model", 22),
        ("Provider", "provider", 9),
        ("Requests", "req", 9),
        ("Min", "min", 9),
        ("P50", "p50", 9),
        ("P95", "p95", 9),
        ("P99", "p99", 9),
        ("Max", "max", 9),
    ]

    def __init__(self, storage: StorageBackend) -> None:
        super().__init__()
        self._storage = storage

    def compose(self) -> ComposeResult:
        with Static(id="perf-chips"):
            yield _PerfChip("P50", "chip-p50")
            yield _PerfChip("P95", "chip-p95")
            yield _PerfChip("P99", "chip-p99")
            yield _PerfChip("Mean", "chip-mean")

        yield Label("LATENCY HISTOGRAM", id="hist-label")
        yield Label("(no data)", id="histogram", markup=True)

        yield Label("PER-MODEL LATENCY", id="model-label")
        table: DataTable[str] = DataTable(id="perf-table", cursor_type="row", zebra_stripes=True)
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

    def refresh_data(self, traces: list[Trace]) -> None:
        """Called every 2s by KeetoApp._poll_storage()."""
        latencies: list[float] = [t.latency_ms for t in traces if t.latency_ms is not None]
        latencies.sort()

        # Update stat chips
        p50 = _percentile(latencies, 50)
        p95 = _percentile(latencies, 95)
        p99 = _percentile(latencies, 99)
        mean = sum(latencies) / len(latencies) if latencies else None

        chips = [
            ("chip-p50", p50),
            ("chip-p95", p95),
            ("chip-p99", p99),
            ("chip-mean", mean),
        ]
        colors = ["green", "yellow", "red", "blue"]
        for (chip_id, val), color in zip(chips, colors, strict=False):
            txt = f"[{color}]{_fmt_lat(val)}[/{color}]" if val is not None else "—"
            try:
                chip_label = self.query_one(f"#{chip_id}", Label)
                chip_label.update(f"[bold]{txt}[/bold]")
            except Exception:
                pass

        # Update histogram
        hist_text = _build_histogram(latencies) if latencies else "(no data)"
        with contextlib.suppress(Exception):
            self.query_one("#histogram", Label).update(hist_text)

        # Per-model breakdown
        model_lats: dict[str, dict[str, object]] = {}
        for trace in traces:
            if trace.latency_ms is None:
                continue
            key = trace.model or "unknown"
            if key not in model_lats:
                model_lats[key] = {
                    "provider": trace.provider or "—",
                    "lats": [],
                }
            model_lats[key]["lats"].append(trace.latency_ms)  # type: ignore[union-attr]

        table = self.query_one(DataTable)
        existing_keys = {str(k.value) for k in table.rows}
        incoming_keys = set(model_lats.keys())

        for key in existing_keys - incoming_keys:
            with contextlib.suppress(Exception):
                table.remove_row(key)

        for model, stats in sorted(model_lats.items()):
            lats: list[float] = sorted(stats["lats"])  # type: ignore[arg-type]
            row_data = [
                model[:22],
                str(stats["provider"])[:9],
                str(len(lats)),
                _fmt_lat(lats[0]),
                _fmt_lat(_percentile(lats, 50)),
                _fmt_lat(_percentile(lats, 95)),
                _fmt_lat(_percentile(lats, 99)),
                _fmt_lat(lats[-1]),
            ]
            if model in existing_keys:
                for col_idx, cell in enumerate(row_data):
                    with contextlib.suppress(Exception):
                        table.update_cell(model, self._MODEL_COLS[col_idx][1], cell)
            else:
                table.add_row(*row_data, key=model)

        hint = self.query_one("#empty-hint")
        hint.display = table.row_count == 0
