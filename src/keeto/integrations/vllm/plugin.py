from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor


class VLLMPlugin(Plugin):
    """
    vLLM serves an OpenAI-compatible REST API, so the OpenAIPlugin captures
    all traffic automatically when the OpenAI SDK is pointed at a vLLM server
    via base_url. This plugin is a named registry marker; no additional
    patching is required.

    Note: spans are tagged provider="openai" because the OpenAI SDK is the
    transport layer. Latency, token counts, and model names are captured
    correctly. Cost is not computed (self-hosted inference has no per-token
    API price).
    """

    name: ClassVar[str] = "vllm"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor

    def uninstall(self) -> None:
        self._monitor = None
