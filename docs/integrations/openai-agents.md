# OpenAI Agents SDK

Keeto integrates with the OpenAI Agents SDK to capture agent loops, handoffs, tool calls, and individual LLM turns.

## Setup

```python
from keeto import monitor
monitor.start()

from agents import Agent, Runner
```

## What's captured

- Agent runs (start, end, final output)
- Each LLM turn within an agent loop
- Tool calls (input, output, latency)
- Agent handoffs
- Token counts and cost per turn

## Basic agent

```python
agent = Agent(
    name="Assistant",
    instructions="You are a helpful assistant.",
    model="gpt-4o-mini",
)
result = Runner.run_sync(agent, "What is the capital of Japan?")
print(result.final_output)
# Span tree: agent_run → llm_turn → (tool_call →) llm_turn → ...
```

## Multi-agent with handoffs

```python
triage_agent = Agent(name="Triage", ...)
specialist_agent = Agent(name="Specialist", ...)

# Handoffs captured as child spans
result = Runner.run_sync(triage_agent, "I need help with billing.")
```

## Tools

```python
from agents import function_tool

@function_tool
def lookup_order(order_id: str) -> str:
    """Look up order status."""
    return f"Order {order_id}: shipped"

agent = Agent(tools=[lookup_order], ...)
```

Tool call input/output is captured as structured attributes on the tool span.
