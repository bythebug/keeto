from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor


class VLLMPlugin(Plugin):
    """
    vLLM serves an OpenAI-compatible REST API, so the OpenAIPlugin already
    captures traffic from users who point openai.OpenAI(base_url=...) at a
    vLLM server. This plugin is a named marker so Keeto's registry can report
    "vllm loaded" and future vLLM-specific enrichment can land here.
    """

    name: ClassVar[str] = "vllm"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor

    def uninstall(self) -> None:
        self._monitor = None
