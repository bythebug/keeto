# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This is **Keeto** — a zero-config, framework-agnostic AI observability library for Python. See `PLAN.md` for the full architecture document, package structure, API design, and 100-issue roadmap (with progress checkboxes).

## Commands

```bash
uv pip install -e ".[dev]"   # install with all dev dependencies
make test                     # run unit tests
make test-unit                # run unit tests with verbose output
make lint                     # ruff check
make fmt                      # ruff format
make typecheck                # pyright strict
make coverage                 # pytest + coverage report
uv run pytest tests/unit/test_span.py -v   # run a single test file
```

## Architecture

- **`src/keeto/core/`** — Monitor, Pipeline, Span/Trace models, Event hierarchy, context propagation
- **`src/keeto/storage/`** — StorageBackend protocol, MemoryStorage (ring buffer, default)
- **`src/keeto/integrations/`** — Per-framework plugins; `_httpx.py` is the shared base transport interceptor used by OpenAI, Anthropic, and any other httpx-based SDK
- **`src/keeto/plugins/`** — Plugin ABC and auto-discovery registry (importlib.metadata entry points)
- **`src/keeto/_pricing.py`** — Provider/model pricing table; `cost_usd()` calculates request cost
- **`src/keeto/analyzers/`**, **`exporters/`**, **`dashboard/`**, **`cli/`** — Milestone 2–6 (stubs in place)

## Key design rules

- The interceptor hot path is **non-blocking**: spans are enqueued to an asyncio.Queue and processed by a background daemon thread. Never add I/O to the interception path.
- All events are **immutable** Pydantic models (`frozen=True` on BaseEvent).
- Span models are **mutable** so plugins can enrich them after capture.
- The global `from keeto import monitor` instance uses `MemoryStorage` and `auto=True` by default.
- Plugin entry point group: `keeto.plugins` — third-party packages auto-load via this group.

## Testing

- Unit tests in `tests/unit/` — no network, no API keys required
- Integration tests in `tests/integration/` — marked `@pytest.mark.integration`, need API key env vars, run nightly in CI
- Use `respx` to mock httpx transport in plugin tests
