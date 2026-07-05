"""
TraceDetailWidget — right-hand panel showing full trace metadata, spans,
attributes, and (from issue #25) the timeline waterfall.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static

from keeto.dashboard.tui.widgets._utils import _fmt_cost, _fmt_lat, _fmt_tokens

if TYPE_CHECKING:
    from keeto.core.span import Span, Trace


# ---------------------------------------------------------------------------
# Section heading helper
# ---------------------------------------------------------------------------

class _SectionHeader(Static):
    DEFAULT_CSS = """
    _SectionHeader {
        color: $text-muted;
        text-style: bold;
        padding: 1 0 0 0;
    }
    """


class _KV(Static):
    """Key-value row."""
    DEFAULT_CSS = """
    _KV {
        layout: horizontal;
        height: 1;
    }
    _KV .kv-key {
        width: 24;
        color: $text-muted;
    }
    _KV .kv-val {
        width: 1fr;
        color: $text;
    }
    """

    def __init__(self, key: str, value: str) -> None:
        super().__init__()
        self._key = key
        self._value = value

    def compose(self) -> ComposeResult:
        yield Label(self._key, classes="kv-key")
        yield Label(self._value, classes="kv-val", markup=True)


# ---------------------------------------------------------------------------
# SpanRow — one row per span in the spans section
# ---------------------------------------------------------------------------

class _SpanRow(Static):
    DEFAULT_CSS = """
    _SpanRow {
        layout: horizontal;
        height: 1;
        padding: 0 0 0 1;
    }
    _SpanRow .sr-name  { width: 26; }
    _SpanRow .sr-model { width: 20; color: $text-muted; }
    _SpanRow .sr-lat   { width: 9;  text-align: right; }
    _SpanRow .sr-cost  { width: 9;  text-align: right; color: $text-muted; }
    _SpanRow .sr-st    { width: 5;  text-align: center; }
    """

    def __init__(self, span: "Span") -> None:
        super().__init__()
        self._span = span

    def compose(self) -> ComposeResult:
        s = self._span
        status = "[red]✗[/red]" if s.status.value == "error" else "[green]✓[/green]"
        yield Label(f"● {s.name[:24]}", classes="sr-name")
        yield Label((s.model or "")[:18], classes="sr-model")
        yield Label(_fmt_lat(s.latency_ms), classes="sr-lat")
        yield Label(_fmt_cost(s.cost_usd or 0), classes="sr-cost")
        yield Label(status, classes="sr-st", markup=True)


# ---------------------------------------------------------------------------
# TraceDetailWidget
# ---------------------------------------------------------------------------

class TraceDetailWidget(Widget):
    """
    Full-detail panel for a selected trace.

    Sections:
      1. Header — trace ID, provider, model, latency, cost, status
      2. Timeline — ASCII waterfall (wired in issue #25)
      3. Spans — one row per span with key fields
      4. Attributes — all span attributes as key-value pairs
    """

    DEFAULT_CSS: ClassVar[str] = """
    TraceDetailWidget {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    #detail-header {
        background: $primary-darken-3;
        padding: 0 1;
        height: auto;
    }
    .timeline-placeholder {
        color: $text-muted;
        padding: 1 0 0 0;
    }
    .section-rule {
        color: $primary-darken-1;
    }
    .empty-hint {
        color: $text-muted;
        padding: 0 0 0 1;
    }
    """

    # Reactive so the panel re-renders when the selected trace changes.
    trace: reactive["Trace | None"] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static(id="detail-header")
        yield Static(id="detail-body")

    def watch_trace(self, trace: "Trace | None") -> None:
        self._rebuild(trace)

    def show(self, trace: "Trace") -> None:
        self.trace = trace

    def _rebuild(self, trace: "Trace | None") -> None:
        header = self.query_one("#detail-header")
        body = self.query_one("#detail-body")
        header.remove_children()
        body.remove_children()

        if trace is None:
            header.mount(
                Label(
                    "[dim]Select a trace to see details[/dim]",
                    markup=True,
                )
            )
            return

        # ------------------------------------------------------------------
        # 1. Header
        # ------------------------------------------------------------------
        status_markup = (
            "[red]✗ error[/red]" if trace.has_error else "[green]✓ ok[/green]"
        )
        title = f"[bold]{trace.trace_id}[/bold]"
        meta_parts = [
            trace.provider or "—",
            trace.model or "—",
            _fmt_lat(trace.latency_ms),
            _fmt_cost(trace.total_cost_usd),
            f"[bold]{_fmt_tokens(trace.total_input_tokens + trace.total_output_tokens)}[/bold] tok",
            status_markup,
        ]
        header.mount(Label(title, markup=True))
        header.mount(Label("  ".join(meta_parts), markup=True))

        # ------------------------------------------------------------------
        # 2. Timeline waterfall (#25)
        # ------------------------------------------------------------------
        from keeto.dashboard.tui.widgets.timeline import TimelineWidget  # noqa: PLC0415

        body.mount(_SectionHeader("TIMELINE"))
        tl = TimelineWidget()
        body.mount(tl)
        # Setting the reactive *after* mount triggers watch_trace once the
        # widget is fully composed.
        self.call_after_refresh(tl.show, trace)

        # ------------------------------------------------------------------
        # 3. Spans
        # ------------------------------------------------------------------
        body.mount(_SectionHeader(f"SPANS  ({len(trace.spans)})"))
        if trace.spans:
            header_row = Static()
            header_row.DEFAULT_CSS = "_SpanRow { height: 1; }"
            for span in trace.spans:
                body.mount(_SpanRow(span))
        else:
            body.mount(Label("[dim]no spans[/dim]", classes="empty-hint", markup=True))

        # ------------------------------------------------------------------
        # 4. Attributes (merged from all spans, de-duped)
        # ------------------------------------------------------------------
        merged: dict[str, str] = {}
        for span in trace.spans:
            for k, v in span.attributes.items():
                if k not in merged:
                    merged[k] = str(v)

        # Surface the most useful attrs first
        priority = [
            "llm.model", "llm.message_count", "llm.finish_reason",
            "llm.stream", "http.status_code", "http.latency_ms",
        ]
        ordered = [(k, merged[k]) for k in priority if k in merged]
        ordered += [(k, v) for k, v in sorted(merged.items()) if k not in priority]

        if ordered:
            body.mount(_SectionHeader("ATTRIBUTES"))
            for k, v in ordered[:20]:  # cap at 20 to avoid overflow
                body.mount(_KV(k, v))

        # Token breakdown if available
        root = trace.root_span
        if root and any(
            x is not None
            for x in [root.input_tokens, root.output_tokens, root.cached_tokens]
        ):
            body.mount(_SectionHeader("TOKENS"))
            if root.input_tokens is not None:
                body.mount(_KV("input", _fmt_tokens(root.input_tokens)))
            if root.cached_tokens:
                body.mount(
                    _KV("cached", f"{_fmt_tokens(root.cached_tokens)} [dim](discounted)[/dim]")
                )
            if root.output_tokens is not None:
                body.mount(_KV("output", _fmt_tokens(root.output_tokens)))
            if root.cost_usd is not None:
                body.mount(_KV("cost", f"[green]{_fmt_cost(root.cost_usd)}[/green]"))
