# OpenAI

Keeto captures all OpenAI API calls — chat completions, streaming, tool calls, embeddings, and the Batch API — automatically.

## Setup

```python
from keeto import monitor
monitor.start()  # auto-detects openai if installed

import openai
client = openai.OpenAI()
```

No changes to your OpenAI client or call sites.

## What's captured

| Field | Source |
|---|---|
| Model | `model` parameter |
| Input tokens | `usage.prompt_tokens` |
| Output tokens | `usage.completion_tokens` |
| Cached tokens | `usage.prompt_tokens_details.cached_tokens` |
| Cost (USD) | Computed from pricing table |
| Latency | Wall clock (first byte to last byte) |
| Tool calls | `tool_calls` in response |
| System prompt | `messages[0].content` where `role == "system"` |
| Finish reason | `choices[0].finish_reason` |

## Streaming

Streaming responses are fully supported. Keeto buffers chunks and records the aggregated token counts when the stream ends.

```python
stream = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Count to 10."}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
# Span is recorded when the stream is exhausted
```

## Tool calls

```python
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What's the weather in Paris?"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        }
    }]
)
# Tool call input/output captured as child spans
```

## Embeddings

```python
response = client.embeddings.create(
    model="text-embedding-3-small",
    input=["Hello", "World"],
)
# Captures: model, input_count, dimensions, cost
```

## Async client

```python
client = openai.AsyncOpenAI()
response = await client.chat.completions.create(...)
# Same capture as sync
```

## Manual wrapping

If auto-detection doesn't work (e.g., custom client setup):

```python
from keeto.integrations.openai import OpenAIPlugin
from keeto import Monitor

monitor = Monitor(auto=False, plugins=[OpenAIPlugin()])
monitor.start()
```
