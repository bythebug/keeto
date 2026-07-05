from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from keeto.plugins.base import Plugin

if TYPE_CHECKING:
    from keeto.core.monitor import Monitor


class KeetoMiddleware:
    """
    FastAPI/Starlette middleware. Creates a Keeto trace per incoming HTTP request
    so that any AI calls made during request handling are grouped under that trace.
    """

    def __init__(self, app: Any, monitor: Monitor) -> None:
        self._app = app
        self._monitor = monitor

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        from keeto.core.context import (
            new_span_id,
            new_trace_id,
            reset_span_id,
            reset_trace_id,
            set_span_id,
            set_trace_id,
        )
        from keeto.core.span import Span, SpanKind, SpanStatus

        tid = new_trace_id()
        sid = new_span_id()
        trace_token = set_trace_id(tid)
        span_token = set_span_id(sid)

        method = scope.get("method", "")
        path = scope.get("path", "")
        query = scope.get("query_string", b"").decode()
        url = f"{path}?{query}" if query else path

        span = Span(
            trace_id=tid,
            span_id=sid,
            name=f"{method} {path}",
            kind=SpanKind.CUSTOM,
            status=SpanStatus.UNSET,
        )
        span.set_attribute("http.method", method)
        span.set_attribute("http.path", path)
        span.set_attribute("http.url", url)

        status_code: int = 500

        async def send_wrapper(message: Any) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
            span.set_attribute("http.status_code", status_code)
            span.finish(status=SpanStatus.OK if status_code < 400 else SpanStatus.ERROR)
        except Exception as exc:
            span.set_attribute("http.status_code", 500)
            span.finish(status=SpanStatus.ERROR, status_message=str(exc))
            raise
        finally:
            self._monitor.emit(span)
            reset_trace_id(trace_token)
            reset_span_id(span_token)


def add_keeto_middleware(app: Any, monitor: Monitor) -> None:
    """Attach KeetoMiddleware to a FastAPI/Starlette app."""
    app.add_middleware(KeetoMiddleware, monitor=monitor)


class FastAPIPlugin(Plugin):
    name: ClassVar[str] = "fastapi"

    def __init__(self) -> None:
        self._monitor: Monitor | None = None

    def install(self, monitor: Monitor) -> None:
        self._monitor = monitor

    def uninstall(self) -> None:
        self._monitor = None
