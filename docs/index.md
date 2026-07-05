---
hide:
  - navigation
  - toc
---

# Keeto — AI Observability for Python

<p class="hero-tagline">Zero-config tracing, cost tracking, and dashboards for every AI call in your Python app. Two lines of code. No rewrites.</p>

<div class="grid cards hero-actions" markdown>

-   [:octicons-rocket-24: __Get started in 2 minutes__](quickstart.md)

-   [:octicons-package-24: __pip install keeto__](#install){ .md-button .md-button--primary }

</div>

---

```python
from keeto import monitor
monitor.start()  # (1)

# Your existing code — completely unchanged
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

1.  That's it. Keeto auto-detects OpenAI, Anthropic, LangChain, LiteLLM, Gemini, Ollama and more — no SDK changes required.

```python
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

## What Keeto does

<div class="grid cards" markdown>

-   :material-lightning-bolt: __Zero config__

    ---

    `monitor.start()` is the entire setup. Keeto scans installed packages and patches their HTTP transport automatically — no wrappers, no decorators, no code changes.

    [:octicons-arrow-right-24: Quickstart](quickstart.md)

-   :material-currency-usd: __Cost & token tracking__

    ---

    Every call captures input tokens, output tokens, cached tokens, and USD cost — computed from a built-in pricing table covering GPT-4o, Claude 3.5, Gemini 1.5, and more.

    [:octicons-arrow-right-24: Configuration](configuration.md)

-   :material-bell-alert: __Budget alerts__

    ---

    Set session, daily, or monthly cost and token budgets. Keeto fires a warning (and optional webhook) the moment a threshold is crossed — before surprise bills arrive.

    [:octicons-arrow-right-24: Configuration](configuration.md#budgets)

-   :material-shield-lock: __PII scrubbing__

    ---

    Enable `scrub_pii=True` to automatically redact emails, SSNs, phone numbers, and custom regex patterns from all captured spans before they touch storage.

    [:octicons-arrow-right-24: Security & PII](security.md)

-   :material-export: __Export everywhere__

    ---

    Export traces to JSON, CSV, OpenTelemetry (OTLP), LangSmith, or MLflow. Filter by time range. Works with any storage backend.

    [:octicons-arrow-right-24: Exporters](exporters/index.md)

-   :material-chart-bar: __Recommendations engine__

    ---

    Rule-based analysis flags oversized prompts, repeated identical calls, high error rates, and cache candidates — actionable findings, not raw data.

    [:octicons-arrow-right-24: Analysis](analysis/index.md)

</div>

---

## Integrations

Keeto auto-detects and patches whichever SDKs you have installed.

<div class="grid cards" markdown>

-   **OpenAI** · chat, embeddings, tools, streaming
-   **Anthropic** · messages, tools, streaming
-   **LangChain** · chains, agents, retrievers
-   **LlamaIndex** · query engines, agents
-   **LiteLLM** · all providers via callback
-   **Google Gemini** · generate_content, streaming
-   **Ollama** · local models
-   **OpenAI Agents SDK** · traces, tool calls
-   **PydanticAI** · agents, tools
-   **FastAPI** · request middleware
-   **vLLM** · local inference server

</div>

[:octicons-arrow-right-24: Integrations overview](integrations/index.md)

---

## Why not just use logging?

<div class="grid" markdown>

<div markdown>

**Without Keeto**

```python
import time, logging

start = time.time()
resp = client.chat.completions.create(...)
elapsed = time.time() - start

logging.info(
    "openai call: model=%s tokens=%d/%d latency=%.0fms",
    resp.model,
    resp.usage.prompt_tokens,
    resp.usage.completion_tokens,
    elapsed * 1000,
)
# Repeat this for every call site.
# No cost, no dashboard, no alerts.
```

</div>

<div markdown>

**With Keeto**

```python
from keeto import monitor
monitor.start()

# Done. Every call is captured.
resp = client.chat.completions.create(...)
```

```
keeto: loaded plugins → openai
```

</div>

</div>

---

## Install { #install }

=== "pip"

    ```bash
    pip install keeto
    ```

=== "uv"

    ```bash
    uv add keeto
    ```

=== "with extras"

    ```bash
    # SQLite persistence + interactive TUI
    pip install "keeto[sqlite,tui]"

    # Everything
    pip install "keeto[tui,web,sqlite,otel]"
    ```

[:octicons-arrow-right-24: Full installation guide](installation.md)

---

## Performance

Keeto's non-blocking pipeline adds **under 1ms overhead** on calls that typically take 500ms–30s.

```
Baseline (no Keeto):  847 ms avg
With Keeto:           849 ms avg   (+0.2%)
```

The interceptor enqueues a lightweight object and returns immediately. Parsing, cost calculation, and storage all happen on a background thread.

[:octicons-arrow-right-24: Performance details](performance.md)
