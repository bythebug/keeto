# Keeto — Architecture & Implementation Plan

## Context

The Python AI ecosystem lacks a standard observability primitive. Every team instruments their own logging, builds their own cost tracking, and cobbles together latency dashboards. Keeto fills this gap: a zero-config, framework-agnostic library that any Python AI app can adopt with two lines of code. The target is the same category of "install it and never think about it" tools as Ruff, uv, and Pydantic.

---

## 1. Overall Vision

Keeto is the **`strace` for AI applications** — a transparent observer layer that captures everything happening between your code and AI providers, with zero rewrites required. It becomes load-bearing infrastructure: developers install it once, and it surfaces data they didn't know they were missing.

**Non-goals**: Keeto is not an agent framework, not a prompt management system, not a fine-tuning tool. It observes and reports.

---

## 2. Architecture

### Interception Strategy

The foundational insight: OpenAI, Anthropic, Gemini, LiteLLM, and Ollama all use `httpx` as their HTTP client. By wrapping httpx's `AsyncTransport`/`Transport` with a custom interceptor at `monitor.start()`, we get transparent capture for the majority of frameworks with **zero user code changes**.

For frameworks with richer hook systems (LangChain callbacks, LlamaIndex events, OpenAI Agents SDK traces), we use native adapters to get semantic context (tool names, agent steps, chain structure) that raw HTTP doesn't expose.

```
AI SDK call
    │
    ▼
httpx transport (patched by Keeto)       ← captures: request bytes, latency, response bytes
    │
    ▼
SDK-specific plugin (optional)           ← enriches: token counts, model, tool names, cost
    │
    ▼
Event Bus  →  asyncio.Queue (non-blocking)
                   │
                   ▼
            Background Worker (daemon)
                   │
           ┌───────┼───────┐
           ▼       ▼       ▼
        Storage  Analyzers  Exporters
```

### Critical Design Properties

- **Non-blocking hot path**: The interceptor only captures timestamps and raw bytes on the calling thread. All parsing, analysis, and storage happens on a background asyncio loop running on a daemon thread.
- **Context propagation**: `contextvars.ContextVar` threads trace IDs through async calls, coroutines, and threads without requiring any user instrumentation.
- **Pluggable everything**: Storage, exporters, analyzers, and framework adapters are all plugins. The core is ~500 lines; the rest is composable.

---

## 3. Package Structure

```
src/keeto/
├── __init__.py               # Public API: monitor, Monitor, Span, Trace
├── core/
│   ├── monitor.py            # Monitor class — the user-facing entry point
│   ├── context.py            # contextvars for trace_id / span_id propagation
│   ├── events.py             # Typed event hierarchy (BaseEvent → LLMRequestEvent, etc.)
│   ├── span.py               # Span + Trace Pydantic models (OTel-compatible schema)
│   └── pipeline.py           # Queue + background worker + batch flush
├── storage/
│   ├── base.py               # StorageBackend Protocol
│   ├── memory.py             # Ring buffer (default, no deps)
│   └── sqlite.py             # aiosqlite backend [extra: sqlite]
├── integrations/
│   ├── _httpx.py             # Base httpx transport wrapper (shared by all httpx SDKs)
│   ├── openai/plugin.py      # OpenAI enrichment (tokens, model, streaming)
│   ├── anthropic/plugin.py
│   ├── langchain/plugin.py   # LangChain BaseCallbackHandler
│   ├── llamaindex/plugin.py  # LlamaIndex EventHandler
│   ├── litellm/plugin.py
│   ├── gemini/plugin.py
│   ├── ollama/plugin.py
│   ├── openai_agents/plugin.py
│   ├── pydantic_ai/plugin.py
│   ├── fastapi/middleware.py
│   └── vllm/plugin.py
├── plugins/
│   ├── base.py               # Plugin ABC + Interceptor Protocol
│   └── registry.py           # Auto-discovery via importlib.metadata entry_points
├── analyzers/
│   ├── cost.py               # Token → USD using pricing DB
│   ├── performance.py        # Latency percentiles, throughput
│   ├── errors.py             # Error pattern detection
│   └── recommendations.py    # Rule engine: cost, perf, reliability suggestions
├── exporters/
│   ├── json.py
│   ├── csv.py
│   └── otel.py               # OpenTelemetry OTLP [extra: otel]
├── dashboard/
│   ├── tui/app.py            # Textual app [extra: tui]
│   └── web/server.py         # FastAPI + SSE [extra: web]
├── cli/main.py               # typer CLI (`keeto` command)
└── _pricing.py               # Provider model pricing table (auto-updated)
```

---

## 4. Public API Design

```python
# Minimal — two lines, done
from keeto import monitor
monitor.start()

# Explicit configuration
from keeto import Monitor
from keeto.integrations.openai import OpenAIPlugin
from keeto.storage.sqlite import SQLiteStorage

monitor = Monitor(
    storage=SQLiteStorage("./keeto.db"),
    plugins=[OpenAIPlugin(), AnthropicPlugin()],
    sample_rate=1.0,         # 0.0–1.0, for high-traffic sampling
    scrub_pii=True,          # redact emails, phone numbers from prompts
)
monitor.start()

# Context manager (auto start/stop)
with monitor:
    await client.chat.completions.create(...)

# Manual span (for custom operations)
with monitor.span("vector-search") as span:
    results = db.similarity_search(query)
    span.set_attribute("result_count", len(results))

# Dashboard
monitor.dashboard()               # TUI (default)
monitor.dashboard(mode="web")     # Browser
monitor.dashboard(mode="rich")    # Rich summary table (no deps)

# Export
monitor.export("traces.json")
monitor.export("traces.csv")
monitor.export(format="otel", endpoint="http://jaeger:4317")

# Analysis
report = monitor.recommendations()
print(report)

# Replay
trace = monitor.traces[-1]
trace.replay()   # re-sends the exact same request
```

No decorators required. No base classes to inherit. No config files.

---

## 5. Event Model

All events inherit from `BaseEvent`. The event hierarchy encodes semantic meaning:

```
BaseEvent
├── LLMRequestStartEvent      provider, model, messages, system_prompt, temperature, stream
├── LLMRequestEndEvent        response, input_tokens, output_tokens, cached_tokens, cost_usd, latency_ms
├── LLMStreamChunkEvent       chunk_index, content, finish_reason
├── ToolCallStartEvent        tool_name, tool_input, call_id
├── ToolCallEndEvent          tool_output, latency_ms, error
├── EmbeddingRequestEvent     input_count, model, dimensions, cost_usd
├── RetryEvent                attempt, reason, delay_ms
├── RateLimitEvent            provider, retry_after_s
├── ErrorEvent                exc_type, message, recoverable
└── CustomEvent               name, attributes            # user-defined
```

Events flow through the pipeline as immutable Pydantic models. The pipeline never mutates events — processors return new events or None (to filter).

---

## 6. Storage Design

```python
class StorageBackend(Protocol):
    async def append(self, span: Span) -> None: ...
    async def get_trace(self, trace_id: str) -> Trace | None: ...
    async def list_traces(self, q: TraceQuery) -> list[Trace]: ...
    async def aggregate(self, agg: Aggregation) -> AggResult: ...
    async def purge(self, older_than: datetime) -> int: ...
```

**MemoryStorage** (default, zero deps):
- Ring buffer of configurable size (default: 1000 traces)
- Thread-safe via `asyncio.Lock`
- Suitable for development and short sessions

**SQLiteStorage** (extra: `keeto[sqlite]`):
- `aiosqlite` for async I/O
- Schema: `traces`, `spans`, `events` tables
- JSON column for attributes (SQLite JSON1 extension)
- Auto-migration on first connect
- Suitable for local persistent storage

**PostgresStorage** (extra: `keeto[postgres]`, v1.0):
- `asyncpg` driver
- Partitioned by date for performance
- Suitable for team/production use

Storage is set at `Monitor` construction. A single global `Monitor` instance (accessible via `from keeto import monitor`) uses `MemoryStorage` by default.

---

## 7. Plugin Architecture

```python
class Plugin(ABC):
    name: ClassVar[str]        # e.g. "openai"
    version: ClassVar[str]

    def install(self, monitor: Monitor) -> None:
        """Register interceptors and subscribe to events."""
        ...

    def uninstall(self) -> None:
        """Undo all patches."""
        ...
```

**Plugin Registry**: Uses `importlib.metadata` entry points. Any installed package can register:
```toml
[project.entry-points."keeto.plugins"]
openai = "keeto.integrations.openai:OpenAIPlugin"
```

**Auto-detection**: When `monitor.start(auto=True)` (default), the registry scans for installed packages matching known names and loads their plugins automatically. Users can override with explicit plugin lists.

**Third-party plugins**: Any developer can publish `keeto-myframework` to PyPI with the entry point, and it auto-loads. No PR required.

---

## 8. Dashboard Architecture

### Terminal UI (`keeto[tui]`)

Built with **Textual** (reactive, CSS-driven TUI framework). Layout:

```
┌─ Keeto ─────────────────────────────────────────────────────────┐
│ [Traces] [Cost] [Performance] [Errors]           Live ● 23 req  │
├──────────────────────┬──────────────────────────────────────────┤
│ ID       Model    ms │  Trace: abc123de                         │
│ ────────────────── │  openai › gpt-4o │ $0.0032 │ 1,234ms      │
│ ▶ abc123  gpt-4o 1.2s│  ─────────────────────────────────────  │
│   def456  claude 0.8s│  ● 0ms    Request Start                  │
│   ghi789  gpt-4o 2.1s│  ● 45ms   Tool Call: search_web          │
│   ...                │  ● 120ms  Tool Response (3 results)       │
│                      │  ● 1234ms Response End                    │
│                      │  ─────────────────────────────────────  │
│                      │  Prompt (2,341 tokens)                    │
│                      │  > You are a helpful assistant...         │
│ Cost: $0.12 today    │                                           │
│ Avg: 1.1s  P95: 3.2s │  ⚠ Recommendation: prompt is 40% larger  │
│                      │    than necessary — consider compressing  │
└──────────────────────┴──────────────────────────────────────────┘
```

Live refresh via Textual reactive workers polling the storage backend.

### Web Dashboard (`keeto[web]`)

**FastAPI** backend with **Server-Sent Events** for real-time updates. Frontend uses **HTMX** (no build step, minimal JS). Auto-opens browser on `monitor.dashboard(mode="web")`.

Routes:
- `GET /` — dashboard HTML
- `GET /api/traces` — paginated trace list
- `GET /api/traces/{id}` — trace detail + spans
- `GET /api/metrics` — cost, latency aggregates
- `GET /api/recommendations` — analysis results
- `GET /api/stream` — SSE event stream for live updates

### Future: VS Code Extension

Extension calls `monitor.dashboard(mode="vscode")` which starts a local FastAPI server and opens a WebView panel pointing to `http://localhost:{port}`.

---

## 9. Technology Decisions

| Concern | Choice | Rationale |
|---|---|---|
| Build backend | `hatchling` | Modern, fast, no legacy baggage |
| Package manager | `uv` | Fast lockfile, compatible with pip |
| Data models | `pydantic v2` | Fast (Rust core), JSON-native, great editor support |
| Async runtime | `anyio` + `asyncio` | Trio compatibility; asyncio is the standard |
| HTTP transport | `httpx` | Used by OpenAI + Anthropic SDKs; custom transport support |
| TUI | `textual` | Best Python TUI, reactive, CSS styling |
| Web | `fastapi` + `htmx` | Standard + no heavy JS build |
| CLI | `typer` | Type-annotated click; autocomplete |
| Type checker | `pyright` (strict) | Faster than mypy, better generics |
| Linter | `ruff` | Fast, consolidates flake8+isort+black |
| Structured logging | `structlog` | Context-aware, JSON-ready |
| Testing mock | `respx` | httpx mock without real API calls |
| Docs | `mkdocs-material` + `mkdocstrings` | Standard for modern Python libs |
| Releases | `git-cliff` + conventional commits | Auto-changelog |

**Core mandatory deps**: `pydantic>=2`, `anyio`, `httpx`, `rich`
**All others are optional extras** — users pay only for what they install.

---

## 10. Tradeoffs

**Patching vs. Wrapping**
Monkey-patching the httpx transport is more transparent (no user code changes) but fragile if an SDK changes its HTTP client. We mitigate this with: per-SDK version pinning in CI tests, graceful fallback if patching fails, and explicit wrapper clients as opt-in (`keeto.wrap(openai_client)`).

**In-process vs. Sidecar**
In-process is simpler to install but shares failure domain with the application. A crash in Keeto's background worker should never affect the main app — all background exceptions are caught, logged, and swallowed. Sidecar mode (OTEL export to an external collector) is offered as an export option for production.

**Memory vs. Disk**
Default in-memory storage means no I/O overhead, but traces are lost on process exit. SQLite adds ~1ms per trace write (async, non-blocking). We default to memory for zero-config and let users opt into SQLite for persistence.

**Auto-detect vs. Explicit plugins**
Auto-detection is magic and can cause surprise behavior. We default to `auto=True` but warn in the console which plugins were loaded, making it auditable. `monitor.start(auto=False, plugins=[...])` disables magic entirely.

---

## 11. Security Considerations

- **PII scrubbing**: Built-in regex scrubber strips email addresses, phone numbers, SSNs, credit card numbers from prompt/response text before storage. Configurable with custom patterns.
- **API key redaction**: HTTP headers `Authorization`, `x-api-key`, `api-key` are always stripped from stored requests.
- **Local-first**: No network calls by default. Keeto never sends data anywhere without explicit exporter configuration.
- **No telemetry**: Keeto collects zero usage telemetry. No pings, no analytics.
- **Data retention**: `storage.purge(older_than=timedelta(days=30))` API; configurable auto-purge.
- **GDPR posture**: All data stays on-machine by default. Export only on explicit user action.
- **Prompt confidentiality**: `store_prompts=False` mode stores only metadata (tokens, cost, latency) without prompt/response content.

---

## 12. Scalability Considerations

- **High-volume sampling**: `sample_rate=0.01` captures 1% of requests for prod traffic. Stratified sampling (always capture errors) planned for v1.0.
- **Ring buffer bounds**: In-memory storage is bounded; won't OOM on long-running services.
- **SQLite for solo dev**: Scales to millions of traces locally.
- **PostgreSQL for teams**: Time-series partitioning; supports 50+ concurrent developers.
- **OTEL export for enterprise**: Offloads storage to Jaeger/Tempo/Grafana; Keeto becomes a thin emitter.
- **Async everywhere**: The pipeline never blocks the event loop. Storage writes are batched and flushed on a timer.

---

## 13. Performance Strategy

Target: **<5% latency overhead** on AI calls (typically 500ms–30s — easy target).

1. **Zero-copy hot path**: Interceptor records `start_time`, enqueues a lightweight `PendingSpan` object, returns immediately. No JSON parsing, no DB writes on the call path.
2. **Lock-free queue**: `asyncio.Queue` (async apps) or `queue.SimpleQueue` (sync apps via dedicated background thread + event loop). Never blocks the caller.
3. **Batch flush**: Events accumulate and flush every 50ms (or 100 events, whichever comes first). Single storage write per batch.
4. **Lazy deserialization**: Raw response bytes stored; only deserialized when queried by dashboard or analyzer.
5. **Background daemon thread**: All processing runs on a daemon thread; dies silently with the process.
6. **Overhead benchmarks**: `make benchmark` runs 100 mock AI calls with/without Keeto and fails CI if overhead >5%.

---

## 14. Testing Strategy

- **Unit tests**: Pure logic — span models, event pipeline, cost calculations, recommendations engine. No network.
- **Integration tests** (`--run-integration` flag): Real API calls. Require env vars. Run in CI nightly, not on every PR.
- **Mock tests**: `respx` to mock httpx transport. Tests interceptor fires correctly without real API calls.
- **Plugin tests**: Each integration has its own test file. `PluginTestCase` base class provides standard scenarios (sync, async, streaming, tool call, error).
- **Property tests**: `hypothesis` for serialization roundtrips and cost calculation edge cases.
- **Performance benchmarks**: `pytest-benchmark` measuring pipeline throughput and per-request overhead.
- **Snapshot tests**: `syrupy` for dashboard rendering and export output stability.

Structure: `tests/unit/`, `tests/integration/`, `tests/benchmarks/`, `tests/snapshots/`

---

## 15. Open-Source Strategy

**License**: MIT

**Governance**: Maintainer-led (BDFL). RFC process for breaking changes via GitHub Discussions (2-week comment period).

**Distribution**: PyPI primary. `uv add keeto` / `pip install keeto`. GitHub Releases with auto-generated changelogs via `git-cliff`.

**Community**: GitHub Discussions, Discord, monthly office hours.

**Growth playbook**:
1. Publish benchmark showing <5% overhead
2. Write "Why we built Keeto" on Substack/dev.to
3. Submit to Awesome Python, Python Weekly, PyCoder's Weekly
4. Conference talks: PyCon, EuroPython, AI Engineer World's Fair
5. Integration partnerships with LangChain/LlamaIndex/PydanticAI maintainers

---

## 16. GitHub Repository Structure

```
keeto/                              ← repo root (keeto project)
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  # test + lint + typecheck on PR
│   │   ├── publish.yml             # PyPI publish on tag
│   │   ├── integration.yml         # nightly integration tests
│   │   └── benchmark.yml           # perf regression on main
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   ├── feature_request.md
│   │   └── integration_request.md
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── labeler.yml
├── src/keeto/
├── tests/
├── docs/
├── examples/
├── benchmarks/
├── pyproject.toml
├── uv.lock
├── CONTRIBUTING.md
├── CHANGELOG.md
├── SECURITY.md
└── LICENSE
```

---

## 17. Documentation Plan

**Engine**: MkDocs + `mkdocs-material` + `mkdocstrings[python]`

```
docs/
├── index.md                  ← hero page: 2-line example, benchmark, integrations list
├── quickstart.md
├── installation.md
├── configuration.md
├── integrations/             ← one page per integration
├── dashboard/tui.md + web.md
├── exporters/
├── analysis/
├── plugins/building-plugins.md
├── api-reference/            ← auto-generated
├── performance.md
└── security.md
```

---

## 18. First 100 GitHub Issues

### Milestone 1: Foundation (v0.1) — Issues 1–20

- [x] 1. `[INFRA]` Initialize project with uv + hatchling + pyproject.toml
- [x] 2. `[INFRA]` Configure ruff, pyright (strict), pre-commit hooks
- [x] 3. `[INFRA]` Set up GitHub Actions CI (test + lint + typecheck on PR)
- [x] 4. `[CORE]` Define `Span` and `Trace` Pydantic v2 models (OTel-compatible schema)
- [x] 5. `[CORE]` Define typed `Event` hierarchy (BaseEvent → all subtypes)
- [x] 6. `[CORE]` Implement `contextvars`-based trace/span ID propagation
- [x] 7. `[CORE]` Implement `MemoryStorage` ring buffer with configurable max size
- [x] 8. `[CORE]` Implement async event pipeline (queue + background worker + batch flush)
- [x] 9. `[CORE]` Implement `Monitor` class: `start()`, `stop()`, `use()`, `span()`
- [x] 10. `[CORE]` Auto-detect installed AI packages and load plugins on `start(auto=True)`
- [x] 11. `[PLUGIN]` Define `Plugin` ABC + `Interceptor` Protocol + plugin registry
- [x] 12. `[INTEGRATION]` httpx `AsyncTransport` wrapper — base interceptor for all httpx SDKs
- [x] 13. `[INTEGRATION]` OpenAI plugin: chat completions capture (sync + async)
- [x] 14. `[INTEGRATION]` OpenAI streaming: capture stream chunks and aggregate
- [x] 15. `[INTEGRATION]` OpenAI: token counting and USD cost calculation
- [x] 16. `[INTEGRATION]` Anthropic plugin: messages API (sync + async)
- [x] 17. `[INTEGRATION]` Anthropic streaming support
- [x] 18. `[COST]` Model pricing database: OpenAI + Anthropic (JSON, auto-updatable)
- [x] 19. `[EXPORT]` JSON exporter (`monitor.export("out.json")`)
- [x] 20. `[TEST]` Unit tests: core spans, events, pipeline, monitor (>80% coverage)

### Milestone 2: Dashboard (v0.2) — Issues 21–40

- [x] 21. `[DASHBOARD]` `monitor.dashboard(mode="rich")` — Rich table summary (no extra deps)
- [x] 22. `[DASHBOARD]` TUI: Textual app skeleton with tab bar + layout
- [x] 23. `[DASHBOARD]` TUI: Trace list widget (scrollable, sortable)
- [x] 24. `[DASHBOARD]` TUI: Trace detail side panel
- [x] 25. `[DASHBOARD]` TUI: Timeline visualization (ASCII waterfall)
- [x] 26. `[DASHBOARD]` TUI: Cost summary panel (today, session, per-model breakdown)
- [x] 27. `[DASHBOARD]` TUI: Performance panel (latency histogram, P50/P95/P99)
- [x] 28. `[DASHBOARD]` TUI: Live refresh via Textual reactive workers
- [x] 29. `[DASHBOARD]` TUI: Search and filter traces by model, provider, status
- [x] 30. `[DASHBOARD]` TUI: Vim-style keyboard navigation (j/k, /, q)
- [x] 31. `[DASHBOARD]` Web: FastAPI + SSE server skeleton (`keeto[web]` extra)
- [x] 32. `[DASHBOARD]` Web: Trace list page (HTMX, no JS build)
- [x] 33. `[DASHBOARD]` Web: Trace detail page with timeline
- [x] 34. `[DASHBOARD]` Web: Real-time updates via Server-Sent Events
- [x] 35. `[DASHBOARD]` Web: Cost over time chart (Chart.js CDN)
- [x] 36. `[DASHBOARD]` Web: Error analysis panel
- [x] 37. `[DASHBOARD]` Web: Recommendations panel
- [x] 38. `[DASHBOARD]` Web: Auto-open browser on `monitor.dashboard(mode="web")`
- [x] 39. `[DASHBOARD]` Dark mode support (TUI + web)
- [x] 40. `[EXPORT]` CSV exporter

### Milestone 3: Integrations (v0.3) — Issues 41–65

- [x] 41. `[STORAGE]` SQLite storage backend with aiosqlite (`keeto[sqlite]` extra)
- [x] 42. `[INTEGRATION]` LangChain `BaseCallbackHandler` plugin
- [x] 43. `[INTEGRATION]` LlamaIndex event/callback handler plugin
- [x] 44. `[INTEGRATION]` LiteLLM plugin (proxy interceptor)
- [x] 45. `[INTEGRATION]` Google Gemini plugin (`google-generativeai`)
- [x] 46. `[INTEGRATION]` Ollama plugin (local model tracing)
- [x] 47. `[INTEGRATION]` OpenAI Agents SDK trace integration
- [x] 48. `[INTEGRATION]` PydanticAI instrument hook
- [x] 49. `[INTEGRATION]` FastAPI middleware (per-request trace context)
- [x] 50. `[INTEGRATION]` vLLM plugin (OpenAI-compatible endpoint)
- [x] 51. `[INTEGRATION]` Tool call tracing: structured input/output capture
- [x] 52. `[INTEGRATION]` Structured output validation tracing (Pydantic parse errors)
- [x] 53. `[INTEGRATION]` Retry detection: count retries, log reason
- [x] 54. `[INTEGRATION]` Rate limit event detection and `RateLimitEvent` emission
- [x] 55. `[INTEGRATION]` Embedding request tracing (model, dimensions, batch size)
- [x] 56. `[INTEGRATION]` Image/multimodal request tracing (vision inputs)
- [x] 57. `[INTEGRATION]` Batch request tracing (OpenAI Batch API)
- [x] 58. `[INTEGRATION]` Parallel tool call visualization (fan-out + join)
- [x] 59. `[COST]` Gemini and Ollama pricing entries
- [x] 60. `[COST]` LiteLLM pricing passthrough
- [x] 61. `[COST]` Cost budget alerts: `monitor.set_budget(daily_usd=10.0)`
- [x] 62. `[COST]` Daily/hourly cost aggregation queries
- [x] 63. `[COST]` Provider cost comparison report
- [x] 64. `[INTEGRATION]` Agent loop detection heuristic (same prompt repeated >N times)
- [x] 65. `[TEST]` Integration test harness with `respx` mocks for all HTTP-based plugins

### Milestone 4: Analysis Engine (v0.4) — Issues 66–80

- [ ] 66. `[ANALYSIS]` Recommendations engine core: rule registry + report formatter
- [ ] 67. `[ANALYSIS]` Rule: prompt size optimization (flag prompts >75% of context window)
- [ ] 68. `[ANALYSIS]` Rule: cache candidates (identical prompt sent >2x in session)
- [ ] 69. `[ANALYSIS]` Rule: model switch suggestions (same task cheaper on another model)
- [ ] 70. `[ANALYSIS]` Rule: context waste (large system prompt repeated per-call)
- [ ] 71. `[ANALYSIS]` Rule: retry loop detection (>3 retries on same prompt)
- [ ] 72. `[ANALYSIS]` Rule: hallucination heuristics (repetition patterns, entropy)
- [ ] 73. `[ANALYSIS]` Cost anomaly detection (>2σ from session mean)
- [ ] 74. `[ANALYSIS]` Latency anomaly detection and slow-prompt log
- [ ] 75. `[ANALYSIS]` Error pattern clustering (group similar errors)
- [ ] 76. `[ANALYSIS]` Token budget tracking: `monitor.set_token_budget(monthly=1_000_000)`
- [ ] 77. `[ANALYSIS]` Conversation growth visualization in dashboard
- [ ] 78. `[ANALYSIS]` Prompt replay: `trace.replay()` — re-sends exact request
- [ ] 79. `[ANALYSIS]` Trace comparison: `monitor.compare(trace_a, trace_b)`
- [ ] 80. `[ANALYSIS]` `monitor.recommendations()` — structured report object + pretty print

### Milestone 5: Export & Ecosystem (v0.5) — Issues 81–90

- [ ] 81. `[EXPORT]` OpenTelemetry OTLP exporter (`keeto[otel]` extra)
- [ ] 82. `[EXPORT]` Jaeger export (via OTLP)
- [ ] 83. `[EXPORT]` LangSmith compatibility adapter
- [ ] 84. `[EXPORT]` MLflow compatibility adapter
- [ ] 85. `[EXPORT]` Prometheus `/metrics` endpoint
- [ ] 86. `[EXPORT]` Webhook notifications on error or cost threshold
- [ ] 87. `[STORAGE]` PostgreSQL storage backend with asyncpg (`keeto[postgres]` extra)
- [ ] 88. `[EXPORT]` Bulk historical export with date range filter
- [ ] 89. `[EXPORT]` Import traces from LangSmith for comparison
- [ ] 90. `[INFRA]` Benchmark CI: enforce <5% overhead on each PR

### Milestone 6: CLI & Polish (v1.0) — Issues 91–100

- [ ] 91. `[CLI]` `keeto` CLI skeleton with typer + shell completion
- [ ] 92. `[CLI]` `keeto traces` — list recent traces (table or JSON)
- [ ] 93. `[CLI]` `keeto dashboard` — launch TUI or web dashboard
- [ ] 94. `[CLI]` `keeto replay <trace-id>` — replay a captured trace
- [ ] 95. `[CLI]` `keeto export [--format json|csv|otel] [--output file]`
- [ ] 96. `[CLI]` `keeto analyze` — print recommendations report
- [ ] 97. `[CLI]` `keeto config [get|set|list]` — manage `~/.keeto/config.toml`
- [ ] 98. `[CLI]` `keeto doctor` — diagnose setup issues
- [ ] 99. `[CLI]` `keeto compare <id1> <id2>` — side-by-side trace diff
- [ ] 100. `[DOCS]` v1.0 documentation complete

---

## Version Roadmap

| Version | Theme | Key Deliverables |
|---|---|---|
| v0.1 | Foundation | Core pipeline, Monitor API, OpenAI + Anthropic, JSON export |
| v0.2 | Dashboard | TUI + web dashboard, live refresh, Rich summary |
| v0.3 | Integrations | LangChain, LlamaIndex, LiteLLM, Gemini, Ollama, SQLite storage |
| v0.4 | Analysis | Recommendations engine, replay, cost anomalies, token budgets |
| v0.5 | Ecosystem | OTEL export, LangSmith/MLflow compat, Prometheus, Webhooks |
| v1.0 | Production | CLI, PostgreSQL, full docs, <5% overhead CI guarantee |
| v1.x | Enterprise | Team auth, RBAC, cloud sync (opt-in), Slack alerts |
| v2.0 | Cloud | Hosted dashboard, VS Code extension, CI integration |
