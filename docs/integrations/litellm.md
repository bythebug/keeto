# LiteLLM

Keeto captures all LiteLLM calls — including its proxy routing, cost passthrough, and model aliasing.

## Setup

```python
from keeto import monitor
monitor.start()

import litellm
```

## What's captured

- Model (after LiteLLM alias resolution)
- Input/output tokens
- Cost (from LiteLLM's own cost calculation when available, otherwise Keeto's pricing table)
- Latency
- Provider routing decisions

## Basic usage

```python
response = litellm.completion(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

## Provider routing

```python
response = litellm.completion(
    model="anthropic/claude-haiku-4-5-20251001",
    messages=[{"role": "user", "content": "Hello!"}],
)
# Captures: provider=anthropic, model=claude-haiku-4-5-20251001
```

## Async

```python
response = await litellm.acompletion(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

## LiteLLM Proxy

When using the LiteLLM proxy server, point your OpenAI client at the proxy. Keeto captures the outbound HTTP calls.

```python
client = openai.OpenAI(base_url="http://localhost:4000", api_key="sk-...")
response = client.chat.completions.create(model="gpt-4o-mini", messages=[...])
```
