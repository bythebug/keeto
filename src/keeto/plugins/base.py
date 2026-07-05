from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor


class Plugin(ABC):
    """Base class for all Keeto plugins."""

    name: ClassVar[str]
    version: ClassVar[str] = "0.1.0"

    @abstractmethod
    def install(self, monitor: Monitor) -> None:
        """Patch SDKs and register event handlers."""
        ...

    @abstractmethod
    def uninstall(self) -> None:
        """Undo all patches."""
        ...

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"
