"""ErrorsView — Errors tab. Full implementation in issue #36 (web) / part of TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from keeto.storage.base import StorageBackend


class ErrorsView(Widget):
    DEFAULT_CSS = """
    ErrorsView {
        align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, storage: StorageBackend) -> None:
        super().__init__()
        self._storage = storage

    def compose(self) -> ComposeResult:
        yield Label("Error analysis panel — issue #36")
