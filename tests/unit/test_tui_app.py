"""Smoke tests for the TUI app skeleton."""

from __future__ import annotations

import pytest
from keeto.dashboard.tui.app import KeetoApp
from keeto.dashboard.tui.widgets.cost import CostView
from keeto.dashboard.tui.widgets.errors import ErrorsView
from keeto.dashboard.tui.widgets.performance import PerformanceView
from keeto.dashboard.tui.widgets.traces import TracesView
from keeto.storage.memory import MemoryStorage


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


class TestKeetoApp:
    def test_instantiates(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        assert app.TITLE == "keeto"

    def test_has_expected_bindings(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        keys = {b.key for b in app.BINDINGS}
        assert "q" in keys
        assert "r" in keys
        assert "/" in keys

    def test_refresh_interval_positive(self) -> None:
        from keeto.dashboard.tui.app import _REFRESH_INTERVAL
        assert _REFRESH_INTERVAL > 0

    @pytest.mark.asyncio
    async def test_compose_runs(self, storage: MemoryStorage) -> None:
        """App composes without raising (headless pilot)."""
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            assert app.query_one(TracesView) is not None
            assert app.query_one(CostView) is not None
            assert app.query_one(PerformanceView) is not None
            assert app.query_one(ErrorsView) is not None

    @pytest.mark.asyncio
    async def test_quit_action(self, storage: MemoryStorage) -> None:
        app = KeetoApp(storage=storage)
        async with app.run_test(headless=True) as pilot:
            await pilot.press("q")
            # App should exit cleanly after q
