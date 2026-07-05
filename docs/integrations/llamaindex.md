# LlamaIndex

Keeto captures LlamaIndex queries, LLM calls, embedding requests, and retrieval events via its event handler system.

## Setup

```python
from keeto import monitor
monitor.start()  # auto-detects llama-index

from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
```

## What's captured

- Query engine calls (query, response)
- LLM completions (model, tokens, cost)
- Embedding requests (model, input count, dimensions)
- Retrieval events (nodes retrieved, scores)
- Reranking events

## Query pipeline

```python
documents = SimpleDirectoryReader("data/").load_data()
index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine()

response = query_engine.query("What is the main theme?")
# Spans: query → retrieve → llm_call
```

## Chat engine

```python
chat_engine = index.as_chat_engine()
response = chat_engine.chat("Tell me more about the setting.")
```

## Manual handler

```python
from keeto.integrations.llamaindex import KeetoEventHandler
from llama_index.core import Settings

Settings.callback_manager.add_handler(KeetoEventHandler(monitor))
```
