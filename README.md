# Keeto

**Zero-config AI observability for Python.** Automatic tracing, cost tracking, and dashboards for every LLM call — plus a `@trace` decorator to instrument your own pipelines.

```python
from keeto import monitor
monitor.start()

# Your existing code — completely unchanged
response = client.chat.completions.create(model="gpt-4o", messages=[...])

monitor.dashboard()
```

```
┌─────────────────────────────────────────────────────────────┐
│  Traces: 42   Cost: $0.0312   Tokens: 18,400   Errors: 0   │
├───────────────┬──────────┬────────┬─────────┬──────────────┤
│ Model         │ Calls    │ P50    │ P95     │ Cost         │
├───────────────┼──────────┼────────┼─────────┼──────────────┤
│ gpt-4o        │ 28       │ 843ms  │ 2.1s    │ $0.0289      │
│ gpt-4o-mini   │ 14       │ 312ms  │ 680ms   │ $0.0023      │
└───────────────┴──────────┴────────┴─────────┴──────────────┘
```

---

## Install

```bash
pip install keeto
```

```bash
# SQLite persistence + interactive TUI
pip install "keeto[sqlite,tui]"

# Browser dashboard
pip install "keeto[sqlite,web]"
```

---

## Two ways to use Keeto

### 1. Auto-detect AI SDK calls

Drop two lines into your app. Keeto scans installed packages and patches their HTTP transport — no wrappers, no code changes.

```python
from keeto import monitor
monitor.start()

# OpenAI, Anthropic, LangChain, Gemini … all captured automatically
```

```
keeto: loaded plugins → openai, anthropic
```

### 2. Instrument your own pipeline

Use `@trace` to add stage-by-stage timing to RAG pipelines, multi-step workflows, or any custom framework:

```python
from keeto import monitor, trace

monitor.start()

@trace("embedding")
def embed(text: str) -> list[float]: ...

@trace("retrieval")
def search(vec: list[float]) -> list[str]: ...

@trace("rerank")
def rerank(docs: list[str], query: str) -> list[str]: ...

@trace("llm")
def generate(docs: list[str]) -> str: ...

# Run your pipeline
answer = generate(rerank(search(embed("What is the capital of France?")), "..."))

monitor.pipeline_breakdown()
```

```
Trace a3f8bc12

embedding        18 ms
retrieval        12 ms
rerank           65 ms
llm            1100 ms
──────────────────────
Total          1195 ms

Slowest stage: llm (92.1%)
```

`@trace` works on sync and async functions. Common stage names (`embedding`, `retrieval`, `llm`, `rerank`, `search`) are mapped to the correct span kind automatically.

---

## Features

| Feature | Details |
|---|---|
| **Auto-detection** | Patches OpenAI, Anthropic, LangChain, LlamaIndex, LiteLLM, Gemini, Ollama, and more at `monitor.start()` |
| **`@trace` decorator** | Instrument any sync or async function as a named, timed span |
| **Cost tracking** | Input tokens, output tokens, cached tokens, and USD cost on every span |
| **Budget alerts** | `monitor.set_budget(daily_usd=10.0)` — fires a warning before surprise bills |
| **Token budgets** | `monitor.set_token_budget(monthly=1_000_000)` |
| **PII scrubbing** | `scrub_pii=True` redacts emails, SSNs, phone numbers from stored spans |
| **Dashboards** | Rich table, interactive TUI (`keeto[tui]`), or browser dashboard (`keeto[web]`) |
| **Pipeline breakdown** | `monitor.pipeline_breakdown()` — stage-by-stage latency table |
| **Recommendations** | `monitor.recommendations()` — flags oversized prompts, repeated calls, cache candidates |
| **Export** | JSON, CSV, OpenTelemetry (OTLP), LangSmith, MLflow |
| **Replay** | `trace.replay()` — re-sends the exact original request |
| **Storage** | In-memory (default), SQLite (`keeto[sqlite]`), PostgreSQL (`keeto[postgres]`) |
| **<1ms overhead** | Non-blocking queue — interceptor enqueues and returns immediately |

---

## Integrations

Keeto auto-detects whichever SDKs you have installed:

- **OpenAI** — chat, embeddings, tools, streaming
- **Anthropic** — messages, tools, streaming
- **LangChain** — chains, agents, retrievers
- **LlamaIndex** — query engines, agents
- **LiteLLM** — all providers via callback
- **Google Gemini** — generate_content, streaming
- **Ollama** — local models
- **OpenAI Agents SDK** — traces, tool calls
- **PydanticAI** — agents, tools
- **FastAPI** — per-request trace context middleware
- **vLLM** — local inference server
- **Custom / own framework** — `@trace` decorator

---

## Configuration

```python
from keeto import Monitor
from keeto.storage.sqlite import SQLiteStorage

monitor = Monitor(
    storage=SQLiteStorage("./keeto.db"),   # persist across restarts
    sample_rate=0.1,                        # capture 10% in production
    scrub_pii=True,                         # redact PII before storage
    store_prompts=True,                     # set False for metadata-only
)
monitor.start()

monitor.set_budget(daily_usd=10.0, session_usd=2.0)
monitor.set_token_budget(monthly=1_000_000)
```

## Manual span context

For fine-grained control, use `monitor.span()` directly to group stages under a named root:

```python
with monitor.span("rag-pipeline") as ctx:
    ctx.set_attribute("query", query)
    vec   = embed(query)
    docs  = search(vec)
    answer = generate(docs, query)
```

---

## Dashboard modes

```python
monitor.dashboard()           # Rich table in terminal (no extra deps)
monitor.dashboard("tui")      # Interactive TUI — requires keeto[tui]
monitor.dashboard("web")      # Browser dashboard — requires keeto[web]
```

---

## CLI

```bash
keeto traces                  # list recent traces
keeto dashboard               # launch TUI
keeto analyze                 # print recommendations
keeto export --format json    # export to file
keeto replay <trace-id>       # re-send a captured request
keeto doctor                  # diagnose setup issues
```

---

## Links

- [Documentation](https://bythebug.github.io/keeto)
- [Quickstart](https://bythebug.github.io/keeto/quickstart/)
- [Custom Instrumentation (@trace)](https://bythebug.github.io/keeto/integrations/custom/)
- [PyPI](https://pypi.org/project/keeto)
- [Changelog](CHANGELOG.md)

---

## License

MIT
