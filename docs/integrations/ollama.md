# Ollama

Keeto traces local Ollama model calls, giving you latency and token visibility for self-hosted models.

## Setup

```python
from keeto import monitor
monitor.start()

import ollama
```

Ollama must be running locally (`ollama serve`).

## What's captured

- Model name (e.g., `llama3`, `mistral`, `phi3`)
- Input/output token counts (from Ollama's response metadata)
- Latency
- Prompt and response text (when `store_prompts=True`)

!!! note
    Cost is not computed for Ollama since local models have no per-token API cost.

## Basic usage

```python
response = ollama.chat(
    model="llama3",
    messages=[{"role": "user", "content": "Why is the sky blue?"}],
)
print(response["message"]["content"])
```

## Streaming

```python
stream = ollama.chat(model="llama3", messages=[...], stream=True)
for chunk in stream:
    print(chunk["message"]["content"], end="")
```

## OpenAI-compatible client

Ollama exposes an OpenAI-compatible endpoint. You can use the OpenAI SDK pointed at Ollama, and the OpenAI plugin will capture it:

```python
client = openai.OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
response = client.chat.completions.create(model="llama3", messages=[...])
```
