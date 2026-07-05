"""FastAPI web dashboard — implemented in Milestone 2 (issues #31–#38)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keeto.storage.base import StorageBackend


def start_web_dashboard(storage: StorageBackend, host: str = "127.0.0.1", port: int = 7842) -> None:
    try:
        import fastapi  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Web dashboard requires fastapi. Install with: pip install keeto[web]"
        ) from exc
    raise NotImplementedError("Web dashboard is planned for v0.2 (issues #31–#38).")
