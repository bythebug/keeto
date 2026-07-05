# Building Plugins

Anyone can build a Keeto plugin for a new AI framework or tool. Plugins auto-load when installed — no PR to the Keeto repo required.

## Plugin ABC

```python
from typing import ClassVar
from keeto.plugins.base import Plugin

class MyFrameworkPlugin(Plugin):
    name: ClassVar[str] = "myframework"
    version: ClassVar[str] = "0.1.0"

    def install(self, monitor) -> None:
        """Patch the framework and subscribe to events."""
        # Monkey-patch the framework's HTTP client or hook system
        self._original_call = myframework.Client.call
        myframework.Client.call = self._intercept

    def uninstall(self) -> None:
        """Restore original behavior."""
        myframework.Client.call = self._original_call

    def _intercept(self, client_self, *args, **kwargs):
        from keeto.core.span import Span, SpanKind, SpanStatus
        from keeto.core.context import get_current_trace_id, new_trace_id, new_span_id
        from datetime import datetime, timezone

        span = Span(
            trace_id=get_current_trace_id() or new_trace_id(),
            span_id=new_span_id(),
            name="myframework.call",
            kind=SpanKind.LLM,
            start_time=datetime.now(timezone.utc),
            provider="myframework",
        )
        try:
            result = self._original_call(client_self, *args, **kwargs)
            span.finish()
            return result
        except Exception as exc:
            span.finish(status=SpanStatus.ERROR, status_message=str(exc))
            raise
        finally:
            self._monitor.emit(span)
```

## Using the httpx transport

Most AI SDKs use httpx. Wrap the SDK client's transport with `RecordingSyncTransport` or `RecordingAsyncTransport`:

```python
from keeto.integrations._httpx import RecordingSyncTransport

class MyPlugin(Plugin):
    name = "myprovider"

    def install(self, monitor) -> None:
        import myprovider_sdk
        self._monitor = monitor
        client = myprovider_sdk.get_http_client()
        original = client._transport
        client._transport = RecordingSyncTransport(
            wrapped=original,
            on_span=self._enrich,
            provider="myprovider",
        )

    def _enrich(self, span, request, response) -> None:
        """Enrich the span from the response and emit it."""
        import json
        data = json.loads(response.content)
        span.model = data.get("model")
        span.input_tokens = data.get("usage", {}).get("input_tokens")
        span.output_tokens = data.get("usage", {}).get("output_tokens")
        self._monitor.emit(span)
```

## Entry point registration

Register your plugin in `pyproject.toml`:

```toml
[project.entry-points."keeto.plugins"]
myprovider = "keeto_myprovider:MyPlugin"
```

When a user installs your package, Keeto auto-loads it on `monitor.start()`.

## Packaging

Name your package `keeto-{framework}` so it's discoverable:

```toml
[project]
name = "keeto-myprovider"
version = "0.1.0"
dependencies = ["keeto>=0.1"]

[project.entry-points."keeto.plugins"]
myprovider = "keeto_myprovider:MyPlugin"
```

## Testing your plugin

Use `respx` to mock httpx calls in tests:

```python
import respx
import httpx
from keeto import Monitor
from keeto.storage.memory import MemoryStorage

def test_my_plugin():
    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False, plugins=[MyPlugin()])
    monitor.start()

    with respx.mock:
        respx.post("https://api.myprovider.com/chat").mock(
            return_value=httpx.Response(200, json={
                "model": "my-model",
                "usage": {"input_tokens": 10, "output_tokens": 20},
            })
        )
        import myprovider_sdk
        myprovider_sdk.chat("Hello")

    assert len(storage._traces) == 1
    trace = list(storage._traces.values())[0]
    assert trace.model == "my-model"
    assert trace.total_input_tokens == 10

    monitor.stop()
```

## Publishing

```bash
uv build
uv publish
```

Submit a link to the [keeto-dev/keeto](https://github.com/keeto-dev/keeto) Discussions to get listed in the integration table.
