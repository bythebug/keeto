# PydanticAI

Keeto captures PydanticAI agent runs, LLM calls, tool invocations, and structured output parsing.

## Setup

```python
from keeto import monitor
monitor.start()

from pydantic_ai import Agent
```

## What's captured

- Agent runs with model, tokens, cost
- Tool calls (name, input, output, latency)
- Structured output validation (including parse errors)
- Retry attempts

## Basic agent

```python
from pydantic_ai import Agent

agent = Agent("openai:gpt-4o-mini", system_prompt="Be concise.")
result = agent.run_sync("What is the speed of light?")
print(result.data)
```

## Structured output

```python
from pydantic import BaseModel

class CityInfo(BaseModel):
    name: str
    population: int
    country: str

agent = Agent("openai:gpt-4o-mini", result_type=CityInfo)
result = agent.run_sync("Tell me about Paris.")
print(result.data.population)
# Captures: parse attempts, validation errors if any
```

## Tools

```python
from pydantic_ai import Agent, RunContext

agent = Agent("openai:gpt-4o-mini")

@agent.tool
async def get_weather(ctx: RunContext, city: str) -> str:
    return f"Sunny in {city}"

result = await agent.run("Weather in Berlin?")
# Tool call captured with input={city: "Berlin"}, output="Sunny in Berlin"
```
