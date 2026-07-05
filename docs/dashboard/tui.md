# TUI Dashboard

An interactive terminal dashboard built with [Textual](https://textual.textualize.io/).

## Install

```bash
pip install "keeto[tui]"
```

## Launch

```python
monitor.dashboard()          # default: TUI
monitor.dashboard(mode="tui")
```

Or from the CLI (reads from a SQLite database):

```bash
keeto dashboard --db keeto.db
keeto dashboard --db keeto.db --mode tui
```

## Layout

```
┌─ Keeto ──────────────────────────────────────────────────────────────────┐
│ [Traces] [Cost] [Performance] [Errors]                    Live ● 23 req  │
├──────────────────────────┬───────────────────────────────────────────────┤
│ ID          Model    ms  │  Trace: abc123de                              │
│ ─────────────────────── │  openai › gpt-4o │ $0.0032 │ 1,234ms         │
│ ▶ abc123de  gpt-4o  1.2s│  ──────────────────────────────────────────  │
│   def456ab  claude  0.8s│  ● 0ms    Request Start                       │
│   ghi789cd  gpt-4o  2.1s│  ● 45ms   Tool Call: search_web              │
│   ...                    │  ● 120ms  Tool Response (3 results)           │
│                          │  ● 1234ms Response End                        │
│                          │  ──────────────────────────────────────────  │
│                          │  Prompt (2,341 tokens)                        │
│                          │  > You are a helpful assistant...             │
│ Cost: $0.12 today        │                                               │
│ Avg: 1.1s  P95: 3.2s    │  ⚠ Prompt is 40% larger than necessary       │
└──────────────────────────┴───────────────────────────────────────────────┘
```

## Tabs

| Tab | Contents |
|---|---|
| **Traces** | Scrollable trace list with model, latency, cost, status |
| **Cost** | Today / session / per-model cost breakdown |
| **Performance** | Latency histogram, P50/P95/P99, throughput |
| **Errors** | Error log grouped by type |

## Keyboard shortcuts

| Key | Action |
|---|---|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `Enter` | Open trace detail |
| `/` | Search / filter |
| `Tab` | Switch tab |
| `r` | Refresh |
| `q` | Quit |

## Filtering

Press `/` to enter a filter query:

```
model:gpt-4o         # filter by model
provider:anthropic   # filter by provider
error                # show only errored traces
cost:>0.01           # traces costing more than $0.01
```

## Live refresh

The TUI polls the storage backend every second. New traces appear automatically as your application runs.

## Dark mode

The TUI respects your terminal's color scheme. Force dark mode with `KEETO_THEME=dark` or light mode with `KEETO_THEME=light`.
