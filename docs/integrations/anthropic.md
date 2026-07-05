# Anthropic

Keeto captures Anthropic Messages API calls including streaming and tool use.

## Setup

```python
from keeto import monitor
monitor.start()

import anthropic
client = anthropic.Anthropic()
```

## What's captured

| Field | Source |
|---|---|
| Model | `model` parameter |
| Input tokens | `usage.input_tokens` |
| Output tokens | `usage.output_tokens` |
| Cache read tokens | `usage.cache_read_input_tokens` |
| Cache creation tokens | `usage.cache_creation_input_tokens` |
| Cost (USD) | Computed from pricing table |
| Latency | Wall clock |
| Stop reason | `stop_reason` |
| Tool use | `content` blocks with `type == "tool_use"` |

## Streaming

Streaming responses are passed through unmodified. Keeto detects the `text/event-stream` content type and does **not** buffer the response body, so tokens are delivered to your application progressively.

**Limitation:** token counts and cost cannot be extracted from streamed responses. The span is recorded with model, latency, and status — but `input_tokens`, `output_tokens`, and `cost_usd` will be `None`.

```python
with client.messages.stream(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Explain recursion."}],
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
# Span recorded: model + latency captured, tokens/cost = None
```

## Tool use

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=[{
        "name": "get_weather",
        "description": "Get current weather",
        "input_schema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    }],
    messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
)
```

## Async client

```python
client = anthropic.AsyncAnthropic()
response = await client.messages.create(...)
```

## Prompt caching

Keeto captures Anthropic's prompt caching token breakdown:

```python
trace = monitor.traces[-1]
root = trace.root_span
print(root.cached_tokens)         # cache read tokens
print(root.attributes.get("llm.cache_creation_tokens"))  # cache write tokens
```
