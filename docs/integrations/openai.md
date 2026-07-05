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

Streaming responses (`stream=True`) are passed through to your application unmodified. Keeto detects the `text/event-stream` content type and does **not** buffer the response, so your application still receives tokens progressively.

**Limitation:** because the response body is not buffered, Keeto cannot extract token counts or cost from streaming calls. The span is still recorded with model, latency, and status — but `input_tokens`, `output_tokens`, and `cost_usd` will be `None`.

```python
stream = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Count to 10."}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
# Span is recorded: model + latency captured, tokens/cost = None
```

If you need cost tracking for streaming calls, use the `usage` field in the final chunk (OpenAI sends it when `stream_options={"include_usage": True}`) and record it via a manual span attribute.

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
