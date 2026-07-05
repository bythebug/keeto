"""
TracesView — left/right split for the Traces tab.

Issue #23 wires up the trace list widget.
Issue #24 wires up the detail panel.
Issue #25 adds the timeline visualization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label, Static

if TYPE_CHECKING:
    from keeto.core.span import Trace
    from keeto.storage.base import StorageBackend


class TracesView(Widget):
    DEFAULT_CSS = """
    TracesView {
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
    .pane-placeholder {
        align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, storage: StorageBackend) -> None:
        super().__init__()
        self._storage = storage
        self._traces: list[Trace] = []

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Static(id="traces-list-pane"):
                yield Label(
                    "Trace list — issue #23",
                    classes="pane-placeholder",
                )
            with Static(id="traces-detail-pane"):
                yield Label(
                    "Trace detail — issue #24",
                    classes="pane-placeholder",
                )

    def refresh_data(self, traces: list[Trace]) -> None:
        """Called by KeetoApp poll loop. Issue #23 will render the list."""
        self._traces = traces
