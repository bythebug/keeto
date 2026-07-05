# Quickstart

Get Keeto running in under two minutes.

## 1. Install

```bash
pip install keeto
```

## 2. Add two lines

```python
from keeto import monitor
monitor.start()
```

That's it. Keeto auto-detects installed AI SDKs (OpenAI, Anthropic, LangChain, etc.) and patches their HTTP transport. Every subsequent AI call is captured.

## 3. Make some AI calls

```python
import openai

client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "What is the capital of France?"}]
)
print(response.choices[0].message.content)
```

## 4. See what was captured

```python
# Rich summary table in the terminal
monitor.dashboard()

# Or view the last trace directly
trace = monitor.traces[-1]
print(f"Model:    {trace.model}")
print(f"Latency:  {trace.latency_ms:.0f}ms")
print(f"Tokens:   {trace.total_input_tokens} in / {trace.total_output_tokens} out")
print(f"Cost:     ${trace.total_cost_usd:.6f}")
```

## 5. Get recommendations

```python
report = monitor.recommendations()
print(report)
# keeto recommendations:
#   [!] [prompt-size] Prompt exceeds 75% of context window on 3 traces
#   [i] [cache-candidate] Identical prompt sent 5 times — consider prompt caching
```

---

## Next steps

- [Configuration](configuration.md) — storage, sampling, PII scrubbing
- [Integrations](integrations/index.md) — framework-specific setup
- [Dashboard](dashboard/tui.md) — interactive TUI and web dashboards
- [CLI](cli.md) — `keeto traces`, `keeto analyze`, `keeto doctor`
