from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor


class PydanticAIPlugin(Plugin):
    name: ClassVar[str] = "pydantic_ai"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._patched_agent_class: Any = None
        self._original_run: Any = None
        self._original_run_sync: Any = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        try:
            import pydantic_ai  # noqa: F401

            self._patch_pydantic_ai()
        except ImportError:
            pass

    def _patch_pydantic_ai(self) -> None:
        try:
            from pydantic_ai import Agent

            original_run = Agent.run
            original_run_sync = Agent.run_sync

            async def patched_run(self_agent: Any, *args: Any, **kwargs: Any) -> Any:
                from keeto.core.context import new_trace_id, reset_trace_id, set_trace_id

                tid = new_trace_id()
                token = set_trace_id(tid)
                try:
                    return await original_run(self_agent, *args, **kwargs)
                finally:
                    reset_trace_id(token)

            def patched_run_sync(self_agent: Any, *args: Any, **kwargs: Any) -> Any:
                from keeto.core.context import new_trace_id, reset_trace_id, set_trace_id

                tid = new_trace_id()
                token = set_trace_id(tid)
                try:
                    return original_run_sync(self_agent, *args, **kwargs)
                finally:
                    reset_trace_id(token)

            Agent.run = patched_run  # type: ignore[method-assign]
            Agent.run_sync = patched_run_sync  # type: ignore[method-assign]

            self._patched_agent_class = Agent
            self._original_run = original_run
            self._original_run_sync = original_run_sync
        except Exception:
            pass

    def uninstall(self) -> None:
        if self._patched_agent_class is not None:
            try:
                if self._original_run is not None:
                    self._patched_agent_class.run = self._original_run
                if self._original_run_sync is not None:
                    self._patched_agent_class.run_sync = self._original_run_sync
            except Exception:
                pass
        self._patched_agent_class = None
        self._original_run = None
        self._original_run_sync = None
