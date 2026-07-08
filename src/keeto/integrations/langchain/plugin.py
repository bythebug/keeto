from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from keeto.core.context import get_current_span_id, get_current_trace_id, new_span_id, new_trace_id
from keeto.core.span import Span, SpanKind, SpanStatus
from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from uuid import UUID

    from keeto.core.monitor import Monitor


def _now() -> datetime:
    return datetime.now(UTC)


def _run_key(run_id: UUID | str) -> str:
    return str(run_id)


class LangChainPlugin(Plugin):
    name: ClassVar[str] = "langchain"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._spans: dict[str, Span] = {}
        self._handler: Any = None
        self._original_configure: Any = None
        self._mgr: Any = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        try:
            import langchain_core.callbacks.manager as _mgr
        except ImportError:
            return

        handler = _LangChainHandler(plugin=self)
        self._handler = handler
        self._mgr = _mgr

        # Monkey-patch _configure so every LangChain runnable automatically
        # gets the Keeto handler injected into its callback manager.
        original_configure = getattr(_mgr, "_configure", None)
        if original_configure is None:
            return

        self._original_configure = original_configure
        _plugin = self

        def _patched_configure(*args: Any, **kwargs: Any) -> Any:
            cm = original_configure(*args, **kwargs)
            if cm is not None:
                existing = {type(h).__name__ for h in getattr(cm, "handlers", [])}
                if "_KeetoLangChainHandler" not in existing:
                    with contextlib.suppress(Exception):
                        cm.add_handler(_plugin._handler, inherit=True)
            return cm

        _mgr._configure = _patched_configure

    def uninstall(self) -> None:
        if self._original_configure is not None and self._mgr is not None:
            self._mgr._configure = self._original_configure
        self._original_configure = None
        self._mgr = None
        self._handler = None
        self._spans.clear()
        self._monitor = None

    def as_handler(self) -> Any:
        """Return a LangChain BaseCallbackHandler that can be passed to chains."""
        if self._handler is None:
            self._handler = _LangChainHandler(plugin=self)
        return self._handler

    # ------------------------------------------------------------------
    # Internal span helpers called by _LangChainHandler
    # ------------------------------------------------------------------

    def _start_span(
        self,
        run_id: UUID | str,
        name: str,
        kind: SpanKind,
        parent_run_id: UUID | str | None = None,
        **attrs: Any,
    ) -> Span:
        trace_id = get_current_trace_id() or new_trace_id()
        span_id = new_span_id()
        parent_span_id: str | None = None
        if parent_run_id is not None:
            parent_key = _run_key(parent_run_id)
            parent_span = self._spans.get(parent_key)
            if parent_span is not None:
                parent_span_id = parent_span.span_id
        if parent_span_id is None:
            parent_span_id = get_current_span_id()

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
        )
        for k, v in attrs.items():
            if v is not None:
                span.set_attribute(k, v)
        self._spans[_run_key(run_id)] = span
        return span

    def _finish_span(
        self,
        run_id: UUID | str,
        status: SpanStatus = SpanStatus.OK,
        status_message: str | None = None,
        **attrs: Any,
    ) -> None:
        key = _run_key(run_id)
        span = self._spans.pop(key, None)
        if span is None:
            return
        for k, v in attrs.items():
            if v is not None:
                span.set_attribute(k, v)
        span.finish(status=status, status_message=status_message)
        if self._monitor:
            self._monitor.emit(span)


class _LangChainHandler:
    """Thin adapter that wraps LangChainPlugin to be a BaseCallbackHandler."""

    def __init__(self, plugin: LangChainPlugin) -> None:
        self._plugin = plugin
        # Try to subclass BaseCallbackHandler at runtime.
        try:
            from langchain_core.callbacks.base import BaseCallbackHandler

            if not isinstance(self, BaseCallbackHandler):
                # Dynamically mix in to satisfy LangChain's isinstance checks.
                self.__class__ = type(
                    "_KeetoLangChainHandler",
                    (self.__class__, BaseCallbackHandler),
                    {},
                )
                BaseCallbackHandler.__init__(self)  # type: ignore[call-arg]
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # LLM callbacks
    # ------------------------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        model = (
            serialized.get("kwargs", {}).get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or serialized.get("name", "")
        )
        span = self._plugin._start_span(
            run_id,
            name="langchain.llm",
            kind=SpanKind.LLM,
            parent_run_id=parent_run_id,
        )
        span.model = model or None
        span.set_attribute("llm.prompt_count", len(prompts))

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        model = (
            serialized.get("kwargs", {}).get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or serialized.get("name", "")
        )
        span = self._plugin._start_span(
            run_id,
            name="langchain.chat_model",
            kind=SpanKind.LLM,
            parent_run_id=parent_run_id,
        )
        span.model = model or None
        msg_count = sum(len(m) if isinstance(m, list) else 1 for m in messages)
        span.set_attribute("llm.message_count", msg_count)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        llm_output: dict[str, Any] = getattr(response, "llm_output", None) or {}
        token_usage: dict[str, Any] = llm_output.get("token_usage", {})
        input_tokens: int | None = token_usage.get("prompt_tokens")
        output_tokens: int | None = token_usage.get("completion_tokens")
        model_name: str | None = llm_output.get("model_name")

        key = _run_key(run_id)
        span = self._plugin._spans.get(key)
        if span and model_name:
            span.model = model_name

        self._plugin._finish_span(
            run_id,
            status=SpanStatus.OK,
            **{
                k: v
                for k, v in {
                    "llm.input_tokens": input_tokens,
                    "llm.output_tokens": output_tokens,
                }.items()
                if v is not None
            },
        )
        if span:
            span.input_tokens = input_tokens
            span.output_tokens = output_tokens

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._plugin._finish_span(run_id, status=SpanStatus.ERROR, status_message=str(error))

    # ------------------------------------------------------------------
    # Chain callbacks
    # ------------------------------------------------------------------

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        name = serialized.get("name") or serialized.get("id", ["chain"])[-1]
        self._plugin._start_span(
            run_id,
            name=f"langchain.chain.{name}",
            kind=SpanKind.CHAIN,
            parent_run_id=parent_run_id,
        )

    def on_chain_end(self, outputs: dict[str, Any], *, run_id: UUID, **kwargs: Any) -> None:
        self._plugin._finish_span(run_id, status=SpanStatus.OK)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._plugin._finish_span(run_id, status=SpanStatus.ERROR, status_message=str(error))

    # ------------------------------------------------------------------
    # Tool callbacks
    # ------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name", "tool")
        span = self._plugin._start_span(
            run_id,
            name=f"langchain.tool.{tool_name}",
            kind=SpanKind.TOOL,
            parent_run_id=parent_run_id,
        )
        span.set_attribute("tool.name", tool_name)
        span.set_attribute("tool.input", input_str[:2000])

    def on_tool_end(self, output: str, *, run_id: UUID, **kwargs: Any) -> None:
        key = _run_key(run_id)
        span = self._plugin._spans.get(key)
        if span:
            span.set_attribute("tool.output", str(output)[:2000])
        self._plugin._finish_span(run_id, status=SpanStatus.OK)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        self._plugin._finish_span(run_id, status=SpanStatus.ERROR, status_message=str(error))
