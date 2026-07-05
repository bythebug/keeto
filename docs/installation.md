# Installation

## Requirements

- Python 3.11+
- No mandatory AI SDK — Keeto works with whatever you have installed

## Core install

```bash
pip install keeto
# or
uv add keeto
```

The core package includes the interceptor, pipeline, MemoryStorage, Rich summary dashboard, JSON/CSV exporters, and the CLI. No extra dependencies beyond `pydantic`, `httpx`, `anyio`, `rich`, and `typer`.

## Extras

Install only what you need:

```bash
# Interactive TUI dashboard (requires textual)
pip install "keeto[tui]"

# Web dashboard (requires fastapi + uvicorn)
pip install "keeto[web]"

# Persistent SQLite storage (requires aiosqlite)
pip install "keeto[sqlite]"

# OpenTelemetry export (requires opentelemetry-sdk + OTLP exporters)
pip install "keeto[otel]"

# PostgreSQL storage (requires asyncpg)
pip install "keeto[postgres]"

# Everything
pip install "keeto[tui,web,sqlite,otel]"
```

## Development install

```bash
git clone https://github.com/bythebug/keeto
cd keeto
uv sync --extra dev
```

## Verify

```bash
keeto doctor
```

`keeto doctor` checks your Python version, installed extras, detected AI SDKs, database, and environment variables. Use it whenever something isn't working as expected.

## Upgrading

```bash
pip install --upgrade keeto
```

Keeto follows semantic versioning. Minor releases (0.x → 0.y) may add new auto-detected plugins; patch releases are always backwards-compatible.
