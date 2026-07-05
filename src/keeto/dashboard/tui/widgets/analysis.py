"""
Analysis tab widget — conversation growth visualization and token budget.

Issue #77: Conversation growth visualization in dashboard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from keeto.core.span import Trace

_BAR_WIDTH = 30


def _bar(value: float, max_value: float, width: int = _BAR_WIDTH) -> str:
    if max_value <= 0:
        return " " * width
    filled = int(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


class AnalysisView(Widget):
    """Conversation growth and recommendations summary."""

    DEFAULT_CSS = """
    AnalysisView {
        height: 1fr;
        overflow-y: auto;
        padding: 1 2;
    }
    AnalysisView Static {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="analysis-content")

    def refresh_data(self, traces: list[Trace]) -> None:
        try:
            content = self.query_one("#analysis-content", Static)
            content.update(self._render(traces))
        except Exception:
            pass

    def _render(self, traces: list[Trace]) -> str:
        if not traces:
            return "[dim]No traces captured yet.[/dim]"

        lines: list[str] = []

        # -- Conversation growth chart --
        lines.append("[bold]Conversation Growth (cumulative tokens)[/bold]")
        lines.append("")

        token_series = []
        cumulative = 0
        for trace in reversed(traces):  # oldest first
            tokens = trace.total_input_tokens + trace.total_output_tokens
            cumulative += tokens
            token_series.append((trace.trace_id[:8], cumulative))

        max_tokens = token_series[-1][1] if token_series else 0

        # Show last 20 data points
        display = token_series[-20:]
        for tid, cum in display:
            bar = _bar(cum, max_tokens)
            lines.append(f"  [dim]{tid}[/dim] {bar} [cyan]{cum:,}[/cyan]")

        lines.append("")

        # -- Per-trace cost sparkline --
        lines.append("[bold]Cost per Trace (USD)[/bold]")
        lines.append("")

        costs = [(t.trace_id[:8], t.total_cost_usd) for t in reversed(traces)]
        max_cost = max((c for _, c in costs), default=0)
        for tid, cost in costs[-20:]:
            bar = _bar(cost, max_cost if max_cost > 0 else 1)
            cost_str = f"${cost:.4f}" if cost > 0 else "[dim]$0.0000[/dim]"
            lines.append(f"  [dim]{tid}[/dim] {bar} {cost_str}")

        lines.append("")

        # -- Token efficiency --
        lines.append("[bold]Token Efficiency (output / input ratio)[/bold]")
        lines.append("")

        for trace in reversed(traces[-10:]):
            inp = trace.total_input_tokens
            out = trace.total_output_tokens
            if inp > 0:
                ratio = out / inp
                bar = _bar(min(ratio, 5), 5)
                lines.append(
                    f"  [dim]{trace.trace_id[:8]}[/dim] {bar} "
                    f"[yellow]{ratio:.2f}x[/yellow] "
                    f"[dim]({inp:,} in → {out:,} out)[/dim]"
                )

        lines.append("")

        # -- Summary stats --
        total_traces = len(traces)
        total_cost = sum(t.total_cost_usd for t in traces)
        total_tokens = sum(t.total_input_tokens + t.total_output_tokens for t in traces)
        error_count = sum(1 for t in traces if t.has_error)

        lines.append("[bold]Session Summary[/bold]")
        lines.append(f"  Traces   : {total_traces:,}")
        lines.append(f"  Tokens   : {total_tokens:,}")
        lines.append(f"  Cost     : ${total_cost:.4f}")
        lines.append(f"  Errors   : {error_count}")

        return "\n".join(lines)
