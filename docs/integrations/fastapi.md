# FastAPI

Keeto's FastAPI middleware attaches a trace context to each incoming HTTP request, so all AI calls made within a request handler share the same trace ID.

## Setup

```python
from fastapi import FastAPI
from keeto import monitor
from keeto.integrations.fastapi import KeetoMiddleware

app = FastAPI()
app.add_middleware(KeetoMiddleware, monitor=monitor)
monitor.start()
```

## What's captured

- Incoming request path, method, status code
- Request latency (total handler time)
- All AI calls made within the handler, linked to the request trace

## Example

```python
from fastapi import FastAPI
from keeto import monitor
from keeto.integrations.fastapi import KeetoMiddleware
import openai

app = FastAPI()
app.add_middleware(KeetoMiddleware, monitor=monitor)
monitor.start()

client = openai.AsyncOpenAI()

@app.post("/chat")
async def chat(message: str):
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": message}],
    )
    return {"reply": response.choices[0].message.content}
# Trace: POST /chat → openai_call
#   latency: 1234ms total, 1187ms in AI call
```

## Trace context propagation

The middleware injects a `trace_id` into the request state and sets it in `contextvars` so nested AI calls are automatically linked:

```python
@app.get("/info")
async def info(request: Request):
    trace_id = request.state.keeto_trace_id  # available if needed
    ...
```
