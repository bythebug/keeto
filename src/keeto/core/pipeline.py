"""
Async event pipeline: queue → background worker → batch flush → storage.

The hot path (interceptor → enqueue) is non-blocking. All storage I/O
happens on a dedicated background asyncio loop running in a daemon thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from keeto.core.span import Span

if TYPE_CHECKING:
    from keeto.storage.base import StorageBackend

log = logging.getLogger(__name__)

_SENTINEL = object()
_FLUSH_INTERVAL_S = 0.05  # 50ms
_BATCH_SIZE = 100


class Pipeline:
    """
    Thread-safe bridge between the calling thread (sync or async) and the
    background event loop that owns all storage writes.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage
        self._queue: asyncio.Queue[Span | object] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="keeto-pipeline", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._started or self._loop is None:
            return
        self._started = False
        self._loop.call_soon_threadsafe(
            self._loop.create_task,  # type: ignore[arg-type]
            self._shutdown(),
        )

    # ------------------------------------------------------------------
    # Hot path — called from any thread
    # ------------------------------------------------------------------

    def emit(self, span: Span) -> None:
        """Enqueue a span for background processing. Never blocks."""
        if self._loop is None or not self._started:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, span)

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._worker())
        self._loop.close()

    async def _worker(self) -> None:
        batch: list[Span] = []

        async def flush() -> None:
            if not batch:
                return
            for span in batch:
                try:
                    await self._storage.append(span)
                except Exception:
                    log.debug("keeto: storage write failed", exc_info=True)
            batch.clear()

        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=_FLUSH_INTERVAL_S)
            except TimeoutError:
                await flush()
                continue

            if item is _SENTINEL:
                await flush()
                await self._storage.close()
                return

            assert isinstance(item, Span)
            batch.append(item)
            if len(batch) >= _BATCH_SIZE:
                await flush()

    async def _shutdown(self) -> None:
        await self._queue.put(_SENTINEL)  # type: ignore[arg-type]
