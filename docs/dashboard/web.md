# Web Dashboard

A browser-based dashboard built with FastAPI and HTMX. No JavaScript build step required.

## Install

```bash
pip install "keeto[web]"
```

## Launch

```python
monitor.dashboard(mode="web")
# Opens http://localhost:7842 in your browser automatically
```

Or from the CLI:

```bash
keeto dashboard --mode web --db keeto.db
keeto dashboard --mode web --db keeto.db --port 8080
```

## Routes

| Route | Description |
|---|---|
| `GET /` | Dashboard home |
| `GET /api/traces` | Paginated trace list (JSON) |
| `GET /api/traces/{id}` | Trace detail + spans |
| `GET /api/metrics` | Cost and latency aggregates |
| `GET /api/recommendations` | Analysis results |
| `GET /api/stream` | SSE event stream for live updates |
| `GET /metrics` | Prometheus metrics endpoint |

## Features

- **Real-time updates** via Server-Sent Events — new traces appear without refresh
- **Cost chart** — hourly/daily cost over time (Chart.js, CDN)
- **Error analysis** — grouped error types with counts and examples
- **Recommendations panel** — rule-based suggestions from the analysis engine
- **Dark mode** — respects `prefers-color-scheme`

## Custom port

```python
from keeto.dashboard.web.server import start_web_dashboard

start_web_dashboard(monitor._storage, port=9000, block=True)
```

## Using in production

The web dashboard is designed for local development and team use — not for public internet exposure. For production observability, use the [OTEL exporter](../exporters/index.md) to send traces to Jaeger, Grafana Tempo, or another collector.

If you do expose the dashboard, put it behind a reverse proxy with authentication.
