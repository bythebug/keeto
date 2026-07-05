from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, ClassVar

from keeto.core.context import new_span_id, new_trace_id
from keeto.core.span import Span, SpanKind, SpanStatus
from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor


class _KeetoTracingProcessor:
    def __init__(self, monitor: Monitor) -> None:
        self._monitor = monitor

    def on_trace_start(self, trace: Any) -> None:
        pass

    def on_trace_end(self, trace: Any) -> None:
        pass

    def on_span_start(self, span: Any) -> None:
        pass

    def on_span_end(self, span: Any) -> None:
        with contextlib.suppress(Exception):
            self._emit(span)

    def _emit(self, agents_span: Any) -> None:
        try:
            from agents.tracing import AgentSpanData, FunctionSpanData, LLMSpanData
        except ImportError:
            AgentSpanData = None
            FunctionSpanData = None
            LLMSpanData = None

        span_data = getattr(agents_span, "span_data", None)

        if LLMSpanData is not None and isinstance(span_data, LLMSpanData):
            kind = SpanKind.LLM
            name = "openai_agents.llm"
        elif FunctionSpanData is not None and isinstance(span_data, FunctionSpanData):
            kind = SpanKind.TOOL
            name = f"openai_agents.tool.{getattr(span_data, 'name', 'unknown')}"
        elif AgentSpanData is not None and isinstance(span_data, AgentSpanData):
            kind = SpanKind.AGENT
            name = f"openai_agents.agent.{getattr(span_data, 'name', 'unknown')}"
        else:
            kind = SpanKind.CUSTOM
            name = "openai_agents.span"

        trace_id = getattr(agents_span, "trace_id", None) or new_trace_id()
        span_id = getattr(agents_span, "span_id", None) or new_span_id()
        parent_id = getattr(agents_span, "parent_id", None)

        keeto_span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_id,
            name=name,
            kind=kind,
            status=SpanStatus.UNSET,
        )

        started_at = getattr(agents_span, "started_at", None)
        ended_at = getattr(agents_span, "ended_at", None)
        if started_at:
            keeto_span.start_time = started_at
        if ended_at:
            keeto_span.end_time = ended_at

        error = getattr(agents_span, "error", None)
        if error:
            keeto_span.finish(status=SpanStatus.ERROR, status_message=str(error))
        else:
            keeto_span.finish(status=SpanStatus.OK)

        if span_data is not None:
            if LLMSpanData is not None and isinstance(span_data, LLMSpanData):
                model = getattr(span_data, "model", None)
                if model:
                    keeto_span.model = model
                    keeto_span.set_attribute("llm.model", model)
                usage = getattr(span_data, "usage", None)
                if usage:
                    keeto_span.input_tokens = getattr(usage, "input_tokens", None)
                    keeto_span.output_tokens = getattr(usage, "output_tokens", None)
            elif FunctionSpanData is not None and isinstance(span_data, FunctionSpanData):
                fn_name = getattr(span_data, "name", None)
                if fn_name:
                    keeto_span.set_attribute("tool.name", fn_name)
                fn_input = getattr(span_data, "input", None)
                if fn_input is not None:
                    keeto_span.set_attribute("tool.input", str(fn_input))
                fn_output = getattr(span_data, "output", None)
                if fn_output is not None:
                    keeto_span.set_attribute("tool.output", str(fn_output))
            elif AgentSpanData is not None and isinstance(span_data, AgentSpanData):
                agent_name = getattr(span_data, "name", None)
                if agent_name:
                    keeto_span.set_attribute("agent.name", agent_name)

        keeto_span.set_attribute("llm.framework", "openai_agents")
        self._monitor.emit(keeto_span)


class OpenAIAgentsPlugin(Plugin):
    name: ClassVar[str] = "openai_agents"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None
        self._processor: _KeetoTracingProcessor | None = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor
        try:
            from agents.tracing import add_trace_processors
        except ImportError:
            return

        self._processor = _KeetoTracingProcessor(monitor)
        add_trace_processors([self._processor])

    def uninstall(self) -> None:
        if self._processor is None:
            return
        try:
            from agents.tracing import set_trace_processors

            set_trace_processors([])
        except Exception:
            pass
        self._processor = None
