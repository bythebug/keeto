from __future__ import annotations

import importlib
import importlib.metadata
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor
    from keeto.plugins.base import Plugin

log = logging.getLogger(__name__)

# Packages that signal a framework is installed → plugin entry-point name
_KNOWN_PACKAGES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "langchain": "langchain",
    "llama-index": "llamaindex",
    "llama_index": "llamaindex",
    "litellm": "litellm",
    "google-generativeai": "gemini",
    "ollama": "ollama",
}

_ENTRY_POINT_GROUP = "keeto.plugins"


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def all(self) -> list[Plugin]:
        return list(self._plugins.values())

    def auto_discover(self, monitor: Monitor) -> list[Plugin]:
        """
        Scan installed packages, load matching plugins from entry points,
        install them, and return the list of loaded plugins.
        """
        installed_names = {dist.metadata["Name"].lower() for dist in importlib.metadata.distributions()}

        # Collect entry-point names to load
        to_load: set[str] = set()
        for pkg_name, ep_name in _KNOWN_PACKAGES.items():
            if pkg_name.lower() in installed_names and ep_name not in self._plugins:
                to_load.add(ep_name)

        loaded: list[Plugin] = []
        eps = importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP)
        ep_map = {ep.name: ep for ep in eps}

        for name in to_load:
            ep = ep_map.get(name)
            if ep is None:
                continue
            try:
                plugin_cls = ep.load()
                plugin: Plugin = plugin_cls()
                plugin.install(monitor)
                self.register(plugin)
                loaded.append(plugin)
                log.debug("keeto: loaded plugin %r", name)
            except Exception:
                log.debug("keeto: failed to load plugin %r", name, exc_info=True)

        return loaded
