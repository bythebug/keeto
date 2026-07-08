# Integrations

Keeto auto-detects installed AI SDKs and patches them at `monitor.start()`. No code changes are required in your application.

## How it works

All major AI Python SDKs (OpenAI, Anthropic, LangChain, LlamaIndex, LiteLLM, Gemini, Ollama) use `httpx` as their HTTP client. Keeto wraps httpx's `AsyncTransport`/`Transport` at startup, giving it transparent access to every request and response — including streaming.

For frameworks with richer hook systems (LangChain callbacks, LlamaIndex events, OpenAI Agents traces), Keeto uses native adapters to capture semantic context like tool names, agent steps, and chain structure that raw HTTP doesn't expose.

## Auto-detection

When `monitor.start(auto=True)` (the default), Keeto scans installed packages and loads the matching plugin:

```
$ python my_app.py
keeto: loaded plugins: openai, anthropic
```

To see what's detected without running your app:

```bash
keeto doctor
```

## Manual plugin loading

```python
from keeto import Monitor
from keeto.integrations.openai import OpenAIPlugin
from keeto.integrations.anthropic import AnthropicPlugin

monitor = Monitor(
    auto=False,
    plugins=[OpenAIPlugin(), AnthropicPlugin()],
)
monitor.start()
```

## Available integrations

| Integration | Package | Plugin class |
|---|---|---|
| [OpenAI](openai.md) | `openai` | `OpenAIPlugin` |
| [Anthropic](anthropic.md) | `anthropic` | `AnthropicPlugin` |
| [LangChain](langchain.md) | `langchain` | `LangChainPlugin` |
| [LlamaIndex](llamaindex.md) | `llama-index` | `LlamaIndexPlugin` |
| [LiteLLM](litellm.md) | `litellm` | `LiteLLMPlugin` |
| [Google Gemini](gemini.md) | `google-generativeai` | `GeminiPlugin` |
| [Ollama](ollama.md) | `ollama` | `OllamaPlugin` |
| [OpenAI Agents SDK](openai-agents.md) | `openai-agents` | `OpenAIAgentsPlugin` |
| [PydanticAI](pydantic-ai.md) | `pydantic-ai` | `PydanticAIPlugin` |
| [FastAPI](fastapi.md) | `fastapi` | Middleware |
| [vLLM](vllm.md) | `vllm` | `VLLMPlugin` |
| [Custom / own framework](custom.md) | — | `@trace` decorator |

## Third-party plugins

Any package can register a Keeto plugin via the `keeto.plugins` entry-point group:

```toml
[project.entry-points."keeto.plugins"]
myframework = "keeto_myframework:MyFrameworkPlugin"
```

Keeto auto-loads it when the package is installed. No PR or registration required.
