from __future__ import annotations
from typing import TYPE_CHECKING
from keeto.plugins.base import Plugin
if TYPE_CHECKING:
    from keeto.core.monitor import Monitor

class LlamaindexPlugin(Plugin):
    name = "llamaindex"
    def install(self, monitor: Monitor) -> None:
        pass
    def uninstall(self) -> None:
        pass
