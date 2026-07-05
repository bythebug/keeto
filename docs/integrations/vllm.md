# vLLM

Keeto captures calls to vLLM's OpenAI-compatible endpoint, giving you latency and token visibility for self-hosted large model inference.

## Setup

vLLM exposes an OpenAI-compatible API. Use the OpenAI SDK pointed at your vLLM server — Keeto's OpenAI plugin captures it automatically.

```python
from keeto import monitor
monitor.start()

import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="token-abc123",  # vLLM accepts any non-empty key
)
```

## What's captured

- Model name (as reported by vLLM)
- Input/output token counts
- Latency (including inference time)
- Streaming chunks

## Basic usage

```python
response = client.chat.completions.create(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    messages=[{"role": "user", "content": "What is vLLM?"}],
)
print(response.choices[0].message.content)
```

## Streaming

```python
stream = client.chat.completions.create(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    messages=[{"role": "user", "content": "Explain PagedAttention."}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

!!! note
    Cost is not computed for vLLM since self-hosted inference has no per-token API cost. Latency tracking is particularly useful for vLLM to measure TTFT (time to first token) and throughput.
