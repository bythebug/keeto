# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-05

### Added
- Zero-config AI observability with `monitor.start()` one-liner
- Auto-discovery and patching of OpenAI, Anthropic, LangChain, LlamaIndex, LiteLLM, Gemini, Ollama, OpenAI Agents, and PydanticAI SDKs
- Span and trace capture with cost, token, and latency tracking
- PII scrubbing for emails, SSNs, phone numbers, and custom patterns
- Sampling (`sample_rate`) to control capture volume
- Session and daily cost budget alerts
- Monthly and daily token budget alerts
- Rich terminal dashboard (`monitor.dashboard()`)
- Export to JSON, CSV, OpenTelemetry, LangSmith, and MLflow
- LangSmith import for trace comparison
- Webhook notifications for errors and budget breaches
- Prometheus metrics export (`PrometheusExporter`)
- SQLite and in-memory storage backends
- Plugin architecture with entry-point auto-discovery
