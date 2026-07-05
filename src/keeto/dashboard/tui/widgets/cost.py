"""CostView — Cost tab. Full implementation in issue #26."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from keeto.storage.base import StorageBackend


class CostView(Widget):
    DEFAULT_CSS = """
    CostView {
        align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, storage: StorageBackend) -> None:
        super().__init__()
        self._storage = storage

    def compose(self) -> ComposeResult:
        yield Label("Cost breakdown — issue #26")
