from __future__ import annotations
from typing import TYPE_CHECKING
from keeto.plugins.base import Plugin
if TYPE_CHECKING:
    from keeto.core.monitor import Monitor

class LangchainPlugin(Plugin):
    name = "langchain"
    def install(self, monitor: Monitor) -> None:
        pass
    def uninstall(self) -> None:
        pass
