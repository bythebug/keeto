# Configuration

## Minimal (zero-config)

```python
from keeto import monitor
monitor.start()
```

This uses in-memory ring-buffer storage (1000 traces), auto-detects installed AI SDKs, and prints which plugins were loaded.

## Full configuration

```python
from keeto import Monitor
from keeto.storage.sqlite import SQLiteStorage
from keeto.integrations.openai import OpenAIPlugin
from keeto.integrations.anthropic import AnthropicPlugin

monitor = Monitor(
    storage=SQLiteStorage("./keeto.db"),
    plugins=[OpenAIPlugin(), AnthropicPlugin()],
    sample_rate=1.0,
    scrub_pii=True,
    store_prompts=True,
)
monitor.start()
```

## Monitor options

| Parameter | Default | Description |
|---|---|---|
| `storage` | `MemoryStorage(max_size=1000)` | Where traces are stored |
| `plugins` | `None` (auto-detect) | Explicit plugin list; disables auto-detection |
| `auto` | `True` | Auto-detect and load plugins for installed SDKs |
| `sample_rate` | `1.0` | Fraction of requests to capture (0.0–1.0) |
| `scrub_pii` | `False` | Redact emails, phone numbers, SSNs from prompt text |
| `store_prompts` | `True` | Store prompt/response content (set False to store metadata only) |

## Storage backends

### MemoryStorage (default)

```python
from keeto.storage.memory import MemoryStorage

monitor = Monitor(storage=MemoryStorage(max_size=500))
```

- Zero dependencies
- Ring buffer — oldest traces drop when full
- Traces are lost on process exit
- Best for: development, scripts, short sessions

### SQLiteStorage

```python
from keeto.storage.sqlite import SQLiteStorage

monitor = Monitor(storage=SQLiteStorage("./keeto.db"))
```

- Requires `pip install "keeto[sqlite]"`
- Persists across process restarts
- Auto-migrates schema on first connect
- Best for: local development with history, CLI usage

### PostgresStorage

```python
from keeto.storage.postgres import PostgresStorage

monitor = Monitor(
    storage=PostgresStorage("postgresql://user:pass@localhost/keeto")
)
```

- Requires `pip install "keeto[postgres]"`
- Date-partitioned for performance
- Best for: production, team environments

## Context manager

```python
with monitor:
    response = await client.chat.completions.create(...)
# monitor.stop() called automatically
```

## Cost budgets

```python
monitor.set_budget(
    daily_usd=10.0,
    session_usd=2.0,
    on_exceed="warn",   # or "stop" to halt new calls
)
```

## Token budgets

```python
monitor.set_token_budget(
    monthly=1_000_000,
    on_exceed="warn",
)
```

## Sampling

For high-traffic services, capture a fraction of requests:

```python
monitor = Monitor(sample_rate=0.1)  # capture 10%
```

Errors are always captured regardless of sample rate.

## PII scrubbing

```python
monitor = Monitor(scrub_pii=True)
```

Scrubs the following patterns from prompt and response text before storage:

- Email addresses
- Phone numbers (US/international)
- Social Security Numbers
- Credit card numbers

## Disabling auto-detection

```python
from keeto.integrations.openai import OpenAIPlugin

monitor = Monitor(
    auto=False,
    plugins=[OpenAIPlugin()],
)
monitor.start()
```

Prints a list of loaded plugins at startup so you can audit what was detected.

## Global singleton

The module-level `monitor` object is a pre-configured singleton with `MemoryStorage` and `auto=True`. For most applications this is all you need:

```python
from keeto import monitor
monitor.start()
```

For custom configuration, instantiate `Monitor` directly and treat it as your own singleton.
