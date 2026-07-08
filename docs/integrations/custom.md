# Custom Instrumentation

If you're building your own framework, RAG pipeline, or multi-stage workflow, Keeto's `@trace` decorator lets you instrument every stage with a single line — no base classes, no config files, no rewrites.

## The `@trace` decorator

```python
from keeto import monitor, trace

monitor.start()

@trace("embedding")
def embed(text: str) -> list[float]:
    ...

@trace("retrieval")
def search(vec: list[float]) -> list[str]:
    ...

@trace("rerank")
def rerank(docs: list[str], query: str) -> list[str]:
    ...

@trace("llm")
def generate(docs: list[str], query: str) -> str:
    ...

# Run your pipeline
def rag(query: str) -> str:
    vec   = embed(query)
    docs  = search(vec)
    docs  = rerank(docs, query)
    return generate(docs, query)

answer = rag("What is the capital of France?")
monitor.pipeline_breakdown()
```

Output:

```
Trace a3f8bc12

embedding        18 ms
retrieval        12 ms
rerank           65 ms
llm            1100 ms
──────────────────────
Total          1202 ms

Slowest stage: llm (91.5%)
```

## Async support

`@trace` works identically on async functions:

```python
@trace("retrieval")
async def search(vec: list[float]) -> list[str]:
    results = await db.similarity_search(vec)
    return results

@trace("llm")
async def generate(docs: list[str]) -> str:
    response = await client.chat.completions.create(...)
    return response.choices[0].message.content
```

## Grouping stages into a single trace

By default, each top-level decorated call starts its own trace. Wrap stages in `monitor.span()` to group them under a shared root:

```python
with monitor.span("rag-pipeline") as ctx:
    ctx.set_attribute("query", query)
    vec   = embed(query)
    docs  = search(vec)
    return generate(docs, query)
```

This produces one trace with a `rag-pipeline` root span and child spans for each stage — visible in the TUI/web dashboard as a waterfall.

## Span kinds — auto-detection

Keeto infers `SpanKind` from the stage name automatically:

| Name pattern | Inferred kind |
|---|---|
| `embedding`, `embed`, `embeddings` | `EMBEDDING` |
| `retrieval`, `retrieve`, `search`, `vector-search`, `rerank` | `RETRIEVAL` |
| `llm`, `generate`, `completion`, `inference`, `chat` | `LLM` |
| `tool`, `tool-call` | `TOOL` |
| `chain`, `pipeline`, `rag` | `CHAIN` |
| `agent` | `AGENT` |
| anything else | `CUSTOM` |

Pass `kind=` explicitly to override:

```python
@monitor.trace("prompt-build", kind=SpanKind.CUSTOM)
def build_prompt(docs: list[str]) -> str:
    ...
```

## Using `monitor.trace()` directly

`@trace` at module level is a shortcut for the global monitor. If you have a custom `Monitor` instance, call `.trace()` on it:

```python
from keeto import Monitor
from keeto.storage.sqlite import SQLiteStorage

monitor = Monitor(storage=SQLiteStorage("./keeto.db"))
monitor.start()

@monitor.trace("embedding")
def embed(text: str) -> list[float]:
    ...
```

## Mixing `@trace` with AI SDK calls

Decorated stages and auto-detected AI SDK calls nest naturally. When `generate()` calls the OpenAI SDK internally, the LLM span becomes a child of the `llm` stage span:

```python
@trace("llm")
async def generate(docs: list[str]) -> str:
    # The openai span is auto-captured as a child of this span
    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "\n".join(docs)}],
    )
    return response.choices[0].message.content
```

## Pipeline breakdown

`monitor.pipeline_breakdown()` prints a latency table for the most recent trace. Pass a specific trace to inspect any historical one:

```python
traces = list(monitor.traces)
for t in traces[-5:]:
    monitor.pipeline_breakdown(trace=t)
```

The breakdown is also visible in the interactive dashboards:

```bash
monitor.dashboard()         # Rich table in terminal
monitor.dashboard("tui")    # Interactive TUI with waterfall
monitor.dashboard("web")    # Browser dashboard
```

## Error handling

Errors are captured automatically — the span status is set to `ERROR` and the exception re-raised, so your existing error handling is unaffected:

```python
@trace("retrieval")
def search(vec: list[float]) -> list[str]:
    raise TimeoutError("vector DB timeout")  # status → ERROR, exception propagates
```

Error spans are always stored regardless of `sample_rate`.
