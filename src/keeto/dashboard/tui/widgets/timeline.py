"""
TimelineWidget — ASCII waterfall chart for spans inside a trace.

Each span occupies one line:
  NAME ─────[████████]──────────── 1,234ms
             ↑                ↑
          offset from        end of span relative to trace start
          trace start

Bar width is scaled to `bar_cols` (default 50). Nested spans are
indented proportionally to their depth in the call tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from keeto.core.span import Span, Trace


_BAR_CHAR = "█"
_FILL_CHAR = "─"
_GUTTER = 2   # indent spaces per depth level
_NAME_WIDTH = 22

# Rich color tags, cycling by nesting depth
_COLORS = ["cyan", "green", "yellow", "magenta", "blue"]


def _depth(span: "Span", all_spans: list["Span"]) -> int:
    parent_ids = {s.span_id for s in all_spans}
    depth = 0
    current = span
    while current.parent_span_id and current.parent_span_id in parent_ids:
        depth += 1
        parent = next(
            (s for s in all_spans if s.span_id == current.parent_span_id), None
        )
        if parent is None or parent is current:
            break
        current = parent
    return depth


def build_waterfall(trace: "Trace", bar_cols: int = 50) -> str:
    """Return Rich-markup string (one line per span) for the waterfall."""
    spans = sorted(trace.spans, key=lambda s: s.start_time)
    if not spans:
        return "[dim]no spans[/dim]"

    trace_start = spans[0].start_time
    trace_end = max(
        (s.end_time or s.start_time for s in spans),
        default=trace_start,
    )
    total_ms = max(
        (trace_end - trace_start).total_seconds() * 1000,
        1.0,
    )

    lines: list[str] = []
    for span in spans:
        offset_ms = max(
            (span.start_time - trace_start).total_seconds() * 1000, 0.0
        )
        dur_ms = span.latency_ms or 0.0

        offset_frac = min(offset_ms / total_ms, 1.0)
        dur_frac = min(dur_ms / total_ms, 1.0 - offset_frac)

        offset_cols = int(offset_frac * bar_cols)
        dur_cols = max(int(dur_frac * bar_cols), 1)
        post_cols = max(bar_cols - offset_cols - dur_cols, 0)

        depth = _depth(span, spans)
        indent = " " * (_GUTTER * depth)
        max_name = _NAME_WIDTH - _GUTTER * depth
        name = span.name[:max_name].ljust(max_name)
        color = _COLORS[depth % len(_COLORS)]

        status = "[red]✗[/red]" if span.status.value == "error" else "[green]✓[/green]"
        lat = f"{dur_ms:.0f}ms" if dur_ms < 1000 else f"{dur_ms / 1000:.2f}s"

        pre = _FILL_CHAR * offset_cols
        bar = f"[{color}]{_BAR_CHAR * dur_cols}[/{color}]"
        post = _FILL_CHAR * post_cols

        lines.append(
            f"{indent}[bold]{name}[/bold] {pre}{bar}{post} {status} [dim]{lat}[/dim]"
        )

    return "\n".join(lines)


class TimelineWidget(Widget):
    """
    ASCII waterfall chart.  Set `trace` to refresh.
    Embedded in TraceDetailWidget (issue #25).
    """

    DEFAULT_CSS: ClassVar[str] = """
    TimelineWidget {
        height: auto;
        padding: 0 0 1 0;
    }
    """

    bar_cols: ClassVar[int] = 50

    trace: reactive["Trace | None"] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static(id="tl-body", markup=True)

    def watch_trace(self, trace: "Trace | None") -> None:
        try:
            body = self.query_one("#tl-body", Static)
        except Exception:
            return
        if trace is None:
            body.update("")
        else:
            body.update(build_waterfall(trace, bar_cols=self.bar_cols))

    def show(self, trace: "Trace") -> None:
        self.trace = trace
