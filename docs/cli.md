# CLI Reference

The `keeto` command is installed automatically with the package. It reads from a SQLite database (`keeto.db` in the current directory, or `~/.keeto/keeto.db`).

!!! tip
    Set `KEETO_DB=/path/to/keeto.db` to point the CLI at a specific database without typing `--db` every time.

## Global options

| Option | Description |
|---|---|
| `--db PATH` | Path to SQLite database (env: `KEETO_DB`) |
| `--help` | Show help |
| `--install-completion` | Install shell completion |
| `--show-completion` | Show completion script |

## `keeto version`

```bash
keeto version
# keeto 0.1.0
```

## `keeto traces`

List recent traces in a Rich table or JSON.

```bash
keeto traces
keeto traces --limit 50
keeto traces --provider openai
keeto traces --model gpt-4o
keeto traces --errors            # only failed traces
keeto traces --format json       # JSON output
keeto traces --db keeto.db
```

| Option | Default | Description |
|---|---|---|
| `--limit, -n` | `20` | Max traces to show |
| `--provider` | | Filter by provider name |
| `--model` | | Filter by model (substring match) |
| `--errors` | | Show only failed traces |
| `--format, -f` | `table` | Output format: `table` or `json` |

## `keeto dashboard`

Launch an interactive dashboard.

```bash
keeto dashboard                  # TUI (default)
keeto dashboard --mode tui
keeto dashboard --mode web
keeto dashboard --mode rich      # Rich summary table, no extra deps
keeto dashboard --port 9000      # Custom port for web mode
```

Requires:

- `--mode tui`: `pip install "keeto[tui]"`
- `--mode web`: `pip install "keeto[web]"`

## `keeto replay`

Replay a captured trace by re-sending the original request.

```bash
keeto replay abc123de
keeto replay abc123          # prefix matching
keeto replay abc123de --dry-run   # print request without sending
```

Requires `store_prompts=True` on the Monitor (the default).

## `keeto export`

Export traces to JSON, CSV, or OpenTelemetry OTLP.

```bash
keeto export                                  # JSON to stdout
keeto export --format json --output out.json
keeto export --format csv --output out.csv
keeto export --format otel --endpoint http://localhost:4317
keeto export --since 2024-01-01 --until 2024-01-31
keeto export --limit 500
```

| Option | Default | Description |
|---|---|---|
| `--format, -f` | inferred or `json` | `json`, `csv`, or `otel` |
| `--output, -o` | stdout | Output file path |
| `--since` | | Start time (ISO-8601) |
| `--until` | | End time (ISO-8601) |
| `--limit, -n` | `10000` | Max traces |
| `--endpoint` | | OTLP endpoint (for `--format otel`) |

## `keeto analyze`

Print a recommendations report.

```bash
keeto analyze
keeto analyze --json
```

## `keeto compare`

Side-by-side comparison of two traces.

```bash
keeto compare abc123de def456ab
keeto compare abc123 def456     # prefix matching
keeto compare abc123de def456ab --json
```

## `keeto config`

Manage `~/.keeto/config.toml`.

```bash
keeto config list
keeto config get db
keeto config set db /path/to/keeto.db
keeto config unset db
```

## `keeto doctor`

Diagnose your Keeto setup.

```bash
keeto doctor
```

Checks:

- Python version (≥3.11 required)
- Core dependencies (pydantic, httpx, rich, typer, anyio)
- Optional extras (aiosqlite, textual, fastapi, opentelemetry, asyncpg)
- Installed AI SDKs (openai, anthropic, langchain, etc.)
- Database (existence, readability, size)
- Config file (`~/.keeto/config.toml`)
- Environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)
- Plugin registry (entry points in `keeto.plugins` group)
