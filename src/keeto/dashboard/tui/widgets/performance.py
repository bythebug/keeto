"""PerformanceView — Performance tab. Full implementation in issue #27."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from keeto.storage.base import StorageBackend


class PerformanceView(Widget):
    DEFAULT_CSS = """
    PerformanceView {
        align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, storage: StorageBackend) -> None:
        super().__init__()
        self._storage = storage

    def compose(self) -> ComposeResult:
        yield Label("Latency histogram, P50/P95/P99 — issue #27")
