# Keeto

**Zero-config AI observability for Python.** Two lines of code. No rewrites. Works with every major AI SDK.

```python
from keeto import monitor
monitor.start()

# Your existing code — completely unchanged
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

Keeto captures latency, token counts, cost, errors, and tool calls across every AI call in your application — automatically.

---

## Why Keeto?

Every Python AI team ends up building the same things: ad-hoc logging, cost tracking spreadsheets, latency dashboards. Keeto is the standard primitive that replaces all of that.

| Without Keeto | With Keeto |
|---|---|
| `print()` debugging | Structured span traces |
| Manual token counting | Automatic token + cost tracking |
| "Why is this slow?" | Latency P50/P95/P99 |
| Surprise API bills | Real-time cost dashboard |
| Guessing at prompt quality | Recommendations engine |

---

## Performance

Keeto's non-blocking pipeline adds **<1ms overhead** on AI calls that typically take 500ms–30s.

```
Baseline (no Keeto):  847ms avg
With Keeto:           849ms avg   (+0.2%)
```

The interceptor enqueues a lightweight object on the calling thread and returns immediately. All parsing, analysis, and storage happen on a background daemon thread.

---

## Integrations

Keeto auto-detects installed SDKs and patches them with zero configuration:

| Provider | Auto-detect | Tokens | Cost | Streaming | Tool calls |
|---|---|---|---|---|---|
| OpenAI | ✓ | ✓ | ✓ | ✓ | ✓ |
| Anthropic | ✓ | ✓ | ✓ | ✓ | ✓ |
| LangChain | ✓ | ✓ | ✓ | ✓ | ✓ |
| LlamaIndex | ✓ | ✓ | ✓ | — | ✓ |
| LiteLLM | ✓ | ✓ | ✓ | ✓ | — |
| Google Gemini | ✓ | ✓ | ✓ | ✓ | — |
| Ollama | ✓ | ✓ | — | ✓ | — |
| OpenAI Agents SDK | ✓ | ✓ | ✓ | — | ✓ |
| PydanticAI | ✓ | ✓ | ✓ | — | ✓ |
| FastAPI | ✓ | — | — | — | — |
| vLLM | ✓ | ✓ | — | ✓ | — |

---

## Install

```bash
pip install keeto
# or
uv add keeto
```

See [Installation](installation.md) for extras (`[tui]`, `[web]`, `[sqlite]`, `[otel]`).
