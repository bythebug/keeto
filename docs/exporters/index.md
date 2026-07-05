# Exporters

Keeto can export captured traces to multiple formats and platforms.

## JSON

```python
monitor.export("traces.json")
# or
monitor.export(format="json")  # writes to stdout
```

```bash
keeto export --format json --output traces.json --db keeto.db
```

Exports all traces as a JSON array. Each trace includes all spans with full attributes.

## CSV

```python
monitor.export("traces.csv")
```

```bash
keeto export --format csv --output traces.csv
```

Flat CSV with one row per trace. Columns: `trace_id`, `provider`, `model`, `latency_ms`, `input_tokens`, `output_tokens`, `cached_tokens`, `cost_usd`, `has_error`, `start_time`.

## OpenTelemetry (OTLP)

```bash
pip install "keeto[otel]"
```

```python
monitor.export(format="otel", endpoint="http://localhost:4317")
```

```bash
keeto export --format otel --endpoint http://localhost:4317
```

Sends traces to any OTLP-compatible collector:

- [Jaeger](https://jaegertracing.io) — `http://localhost:4317`
- [Grafana Tempo](https://grafana.com/oss/tempo/) — configure via OTLP receiver
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [Honeycomb](https://www.honeycomb.io)
- [Datadog](https://www.datadoghq.com) — via OTLP ingest

## LangSmith

```python
monitor.export(format="langsmith", project_name="my-project")
```

Requires `LANGCHAIN_API_KEY` environment variable. Uploads traces to [LangSmith](https://smith.langchain.com) for comparison and evaluation.

### Import from LangSmith

```python
count = monitor.import_langsmith(project_name="my-project", limit=100)
print(f"Imported {count} traces")
```

## MLflow

```python
monitor.export(format="mlflow", experiment_name="my-experiment")
```

Logs traces as MLflow runs. Requires a running MLflow server (`mlflow server`).

## Prometheus

When using the web dashboard, a `/metrics` endpoint is automatically available:

```
http://localhost:7842/metrics
```

Metrics exposed:

| Metric | Type | Description |
|---|---|---|
| `keeto_requests_total` | Counter | Total AI requests by provider/model |
| `keeto_request_duration_seconds` | Histogram | Request latency |
| `keeto_cost_usd_total` | Counter | Cumulative cost |
| `keeto_errors_total` | Counter | Error count by type |
| `keeto_tokens_total` | Counter | Token usage by type (input/output/cached) |

## Webhook notifications

```python
monitor.set_webhook(
    url="https://hooks.slack.com/services/...",
    on_error=True,
    on_cost_threshold=5.0,  # USD
)
```

Sends a JSON POST to the webhook URL when an error occurs or the daily cost threshold is exceeded.

## Date range filtering

All exporters support `since` / `until` filters:

```python
monitor.export("january.json", since="2024-01-01", until="2024-01-31")
```

```bash
keeto export --format json --since 2024-01-01 --until 2024-01-31
```
