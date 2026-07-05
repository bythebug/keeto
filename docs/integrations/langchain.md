# LangChain

Keeto integrates with LangChain via a `BaseCallbackHandler`, capturing chain structure, LLM calls, tool invocations, and token usage.

## Setup

```python
from keeto import monitor
monitor.start()  # auto-detects langchain

from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o-mini")
```

## What's captured

- LLM call start/end with model, tokens, cost
- Chain start/end (e.g., `LLMChain`, `ConversationalRetrievalChain`)
- Tool calls and results
- Agent actions and observations
- Errors with full exception detail

## Chains

```python
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

chain = LLMChain(
    llm=llm,
    prompt=PromptTemplate.from_template("Summarize: {text}"),
)
result = chain.invoke({"text": "Long article..."})
# Span tree: chain → llm_call
```

## Agents

```python
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain.tools import tool

@tool
def search(query: str) -> str:
    """Search the web."""
    return f"Results for: {query}"

agent = create_openai_tools_agent(llm, [search], prompt)
executor = AgentExecutor(agent=agent, tools=[search])
result = executor.invoke({"input": "Who won the 2024 Olympics?"})
# Captures: agent loop, each tool call, final answer
```

## Manual callback

If you need to attach the plugin explicitly instead of relying on auto-detection:

```python
from keeto import Monitor
from keeto.integrations.langchain import LangchainPlugin

monitor = Monitor(auto=False, plugins=[LangchainPlugin()])
monitor.start()

from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o-mini")
```
