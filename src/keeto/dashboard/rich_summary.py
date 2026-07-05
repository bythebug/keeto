"""
Rich-based terminal dashboard for Keeto. No extra deps beyond rich (already required).

Displays a summary stats panel followed by a formatted trace table.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

from rich.columns import Columns
from rich.console import Console
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from keeto.core.span import Trace

_console = Console()


def _fmt_latency(ms: float | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def _fmt_cost(usd: float) -> str:
    if usd == 0:
        return "—"
    if usd < 0.0001:
        return f"${usd:.6f}"
    return f"${usd:.4f}"


def _fmt_tokens(n: int) -> str:
    if n == 0:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def render(traces: list[Trace], console: Console | None = None, limit: int = 50) -> None:
    con = console or _console

    if not traces:
        con.print(
            Panel(
                "[yellow]No traces captured yet.[/yellow]\n\n"
                "Start your monitor and make some AI calls:\n\n"
                "  [dim]from keeto import monitor[/dim]\n"
                "  [dim]monitor.start()[/dim]",
                title="[bold cyan]keeto[/bold cyan]",
                border_style="dim",
            )
        )
        return

    display = traces[:limit]

    # ------------------------------------------------------------------
    # Compute summary stats
    # ------------------------------------------------------------------
    total_cost = sum(t.total_cost_usd for t in traces)
    error_count = sum(1 for t in traces if t.has_error)
    latencies = [t.latency_ms for t in traces if t.latency_ms is not None]
    avg_latency = statistics.mean(latencies) if latencies else None
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) >= 2 else None
    total_input = sum(t.total_input_tokens for t in traces)
    total_output = sum(t.total_output_tokens for t in traces)

    models: dict[str, int] = {}
    for t in traces:
        if t.model:
            models[t.model] = models.get(t.model, 0) + 1
    top_model = max(models, key=lambda k: models[k]) if models else None

    # ------------------------------------------------------------------
    # Stats panels
    # ------------------------------------------------------------------
    def stat(label: str, value: str, style: str = "bold white") -> Panel:
        return Panel(
            Text(value, style=style, justify="center"),
            title=f"[dim]{label}[/dim]",
            border_style="dim",
            padding=(0, 1),
        )

    error_style = "bold red" if error_count else "bold green"
    error_val = f"{error_count} error{'s' if error_count != 1 else ''}" if error_count else "0 errors"

    stats = [
        stat("traces", str(len(traces))),
        stat("total cost", _fmt_cost(total_cost), "bold green"),
        stat("avg latency", _fmt_latency(avg_latency)),
        stat("p95 latency", _fmt_latency(p95_latency), "dim white"),
        stat("tokens in/out", f"{_fmt_tokens(total_input)} / {_fmt_tokens(total_output)}"),
        stat("errors", error_val, error_style),
    ]
    if top_model:
        stats.append(stat("top model", top_model, "bold cyan"))

    con.print()
    con.print(Padding(Columns(stats, equal=True, expand=True), (0, 1)))

    # ------------------------------------------------------------------
    # Trace table
    # ------------------------------------------------------------------
    table = Table(
        title=f"[bold]Recent Traces[/bold] [dim](showing {len(display)} of {len(traces)})[/dim]",
        show_lines=False,
        header_style="bold dim",
        border_style="dim",
        row_styles=["", "dim"],
        expand=True,
    )
    table.add_column("Trace ID", style="dim", width=10, no_wrap=True)
    table.add_column("Provider", width=11)
    table.add_column("Model", width=24, no_wrap=True)
    table.add_column("Latency", justify="right", width=9)
    table.add_column("In", justify="right", width=7)
    table.add_column("Out", justify="right", width=7)
    table.add_column("Cost", justify="right", width=9)
    table.add_column("Status", width=9)

    for trace in display:
        status_text = Text("✗ error", style="red") if trace.has_error else Text("✓ ok", style="green")
        lat_ms = trace.latency_ms
        lat_style = ""
        if lat_ms is not None and p95_latency is not None and lat_ms > p95_latency:
            lat_style = "yellow"

        table.add_row(
            trace.trace_id[:8],
            trace.provider or "—",
            (trace.model or "—")[:24],
            Text(_fmt_latency(lat_ms), style=lat_style),
            _fmt_tokens(trace.total_input_tokens),
            _fmt_tokens(trace.total_output_tokens),
            _fmt_cost(trace.total_cost_usd),
            status_text,
        )

    con.print(Padding(table, (0, 1)))
    con.print()
