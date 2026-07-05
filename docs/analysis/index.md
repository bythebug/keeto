# Analysis Engine

Keeto's analysis engine runs a set of rules over your captured traces and surfaces actionable recommendations.

## Getting recommendations

```python
report = monitor.recommendations()
print(report)
```

```
keeto recommendations:
  [!] [prompt-size] 3 traces have prompts exceeding 75% of the context window
  [!] [cache-candidate] Identical prompt sent 6 times — consider prompt caching
  [i] [model-switch] Task complexity suggests gpt-4o-mini could replace gpt-4o (est. 85% cost saving)
  [i] [context-waste] System prompt repeated verbatim on every call (2,341 tokens each)
```

```bash
keeto analyze --db keeto.db
keeto analyze --db keeto.db --json
```

## Rules

### Prompt size

**Trigger**: Any prompt exceeding 75% of the model's context window.

**Why it matters**: Prompts near the context limit leave little room for responses and increase cost. Often caused by including too much retrieved context or conversation history.

### Cache candidate

**Trigger**: The same prompt (or prompt prefix) sent more than twice in a session.

**Why it matters**: Both OpenAI and Anthropic support prompt caching. Identical system prompts or repeated context blocks can be cached for significant cost reduction.

### Model switch suggestion

**Trigger**: Tasks that appear straightforward (short prompt, short response, no tools) being sent to a high-capability model.

**Why it matters**: `gpt-4o-mini` and `claude-haiku` are 10–20× cheaper than their flagship counterparts and perform identically on simple tasks.

### Context waste

**Trigger**: A large system prompt repeated verbatim on every call.

**Why it matters**: Prompt caching on Anthropic and OpenAI can cache static system prompts, reducing cost by up to 90% on repeated calls.

### Retry loop

**Trigger**: More than 3 retries on the same prompt.

**Why it matters**: Persistent retry loops indicate a structural problem — bad tool output format, model confusion, or a malformed prompt.

### Hallucination heuristics

**Trigger**: Response exhibits high repetition or low entropy patterns.

**Why it matters**: Repetitive or low-entropy outputs often indicate model confusion or degeneration. Useful as a signal to add output validation.

### Cost anomaly

**Trigger**: Any single trace costing more than 2 standard deviations above the session mean.

**Why it matters**: Cost spikes usually indicate an unexpectedly large prompt (context stuffing, runaway agent loop, or accidental debug dump).

### Latency anomaly

**Trigger**: Traces with latency more than 2σ above the session mean.

**Why it matters**: Slow traces often point to large prompts, streaming stalls, or rate-limit retries adding latency.

### Error pattern clustering

Groups similar errors by type and message prefix so you can see which error is occurring most frequently rather than reading individual trace logs.

## Replay

Replay a captured trace to re-send the exact same request:

```python
trace = monitor.traces[-1]
response = trace.replay()
```

```bash
keeto replay abc123de --db keeto.db
keeto replay abc123de --db keeto.db --dry-run  # print request without sending
```

Replay requires `store_prompts=True` (the default) on the Monitor.

## Trace comparison

```python
comparison = monitor.compare(trace_a, trace_b)
print(comparison)
```

```
keeto: trace comparison
  Field                       A              B              Δ
  ────────────────────────────────────────────────────────
  Trace ID              abc123de       def456ab
  Model                   gpt-4o    gpt-4o-mini
  Latency                 1,234ms         892ms        -342ms
  Cost (USD)         $0.003200     $0.000240    -$0.002960
  Input tokens              2,341         2,341              0
  Output tokens               187           201            +14
```

```bash
keeto compare abc123de def456ab --db keeto.db
```

## Token budget tracking

```python
monitor.set_token_budget(monthly=1_000_000, on_exceed="warn")

summary = monitor.token_summary()
print(summary)
# {"total_input": 450000, "total_output": 92000, "budget_monthly": 1000000, ...}
```

## Cost budget

```python
monitor.set_budget(daily_usd=10.0, on_exceed="warn")

summary = monitor.cost_summary()
print(summary)
# {"session_usd": 0.42, "today_usd": 3.18, "budget_daily_usd": 10.0, ...}
```
