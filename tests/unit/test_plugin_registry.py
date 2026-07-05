"""Tests for PluginRegistry."""

from __future__ import annotations

from importlib.metadata import EntryPoint
from unittest.mock import MagicMock, patch

import pytest

from keeto.plugins.registry import PluginRegistry


def _make_plugin(name: str) -> MagicMock:
    p = MagicMock()
    p.name = name
    return p


class TestPluginRegistry:
    def test_register_and_get(self) -> None:
        reg = PluginRegistry()
        p = _make_plugin("openai")
        reg.register(p)
        assert reg.get("openai") is p

    def test_get_missing_returns_none(self) -> None:
        reg = PluginRegistry()
        assert reg.get("nonexistent") is None

    def test_all_returns_registered_plugins(self) -> None:
        reg = PluginRegistry()
        p1 = _make_plugin("openai")
        p2 = _make_plugin("anthropic")
        reg.register(p1)
        reg.register(p2)
        result = reg.all()
        assert p1 in result
        assert p2 in result

    def test_all_empty_initially(self) -> None:
        reg = PluginRegistry()
        assert reg.all() == []

    def test_auto_discover_no_known_packages_installed(self) -> None:
        reg = PluginRegistry()
        monitor = MagicMock()
        with patch("importlib.metadata.distributions", return_value=[]):
            loaded = reg.auto_discover(monitor)
        assert loaded == []

    def test_auto_discover_loads_matching_plugin(self) -> None:
        reg = PluginRegistry()
        monitor = MagicMock()

        fake_dist = MagicMock()
        fake_dist.metadata = {"Name": "openai"}

        plugin_cls = MagicMock()
        plugin_instance = MagicMock()
        plugin_instance.name = "openai"
        plugin_cls.return_value = plugin_instance

        fake_ep = MagicMock(spec=EntryPoint)
        fake_ep.name = "openai"
        fake_ep.load.return_value = plugin_cls

        with (
            patch("importlib.metadata.distributions", return_value=[fake_dist]),
            patch("importlib.metadata.entry_points", return_value=[fake_ep]),
        ):
            loaded = reg.auto_discover(monitor)

        assert plugin_instance in loaded
        plugin_instance.install.assert_called_once_with(monitor)

    def test_auto_discover_skips_already_registered(self) -> None:
        reg = PluginRegistry()
        monitor = MagicMock()
        existing = _make_plugin("openai")
        reg.register(existing)

        fake_dist = MagicMock()
        fake_dist.metadata = {"Name": "openai"}

        with patch("importlib.metadata.distributions", return_value=[fake_dist]):
            loaded = reg.auto_discover(monitor)

        assert loaded == []

    def test_auto_discover_handles_load_exception(self) -> None:
        reg = PluginRegistry()
        monitor = MagicMock()

        fake_dist = MagicMock()
        fake_dist.metadata = {"Name": "openai"}

        fake_ep = MagicMock(spec=EntryPoint)
        fake_ep.name = "openai"
        fake_ep.load.side_effect = RuntimeError("load failed")

        with (
            patch("importlib.metadata.distributions", return_value=[fake_dist]),
            patch("importlib.metadata.entry_points", return_value=[fake_ep]),
        ):
            loaded = reg.auto_discover(monitor)

        assert loaded == []

    def test_auto_discover_skips_ep_not_in_map(self) -> None:
        reg = PluginRegistry()
        monitor = MagicMock()

        fake_dist = MagicMock()
        fake_dist.metadata = {"Name": "openai"}

        with (
            patch("importlib.metadata.distributions", return_value=[fake_dist]),
            patch("importlib.metadata.entry_points", return_value=[]),
        ):
            loaded = reg.auto_discover(monitor)

        assert loaded == []
