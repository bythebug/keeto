# Security

## Local-first

Keeto **never sends data anywhere** without explicit exporter configuration. By default:

- All trace data stays in process memory (or SQLite on disk)
- No network calls are made by Keeto itself
- No usage telemetry, no pings, no analytics

## API key redaction

HTTP headers `Authorization`, `x-api-key`, and `api-key` are **always stripped** from stored request data. Your API keys are never written to disk or memory by Keeto.

## PII scrubbing

Enable automatic redaction of common PII patterns from prompt and response text:

```python
monitor = Monitor(scrub_pii=True)
```

Patterns scrubbed:

| Pattern | Example | Replacement |
|---|---|---|
| Email addresses | `user@example.com` | `[EMAIL]` |
| US phone numbers | `(555) 867-5309` | `[PHONE]` |
| Social Security Numbers | `123-45-6789` | `[SSN]` |
| Credit card numbers | `4111 1111 1111 1111` | `[CARD]` |

Custom patterns:

```python
monitor = Monitor(
    scrub_pii=True,
    pii_patterns=[r"\bACCT-\d{8}\b"],  # internal account IDs
)
```

## Storing only metadata

If you don't want prompt/response content stored at all:

```python
monitor = Monitor(store_prompts=False)
```

This stores only metadata: tokens, cost, latency, model, provider, status. Prompt and response text are never written.

## Data retention

```python
import asyncio
from datetime import timedelta

# Delete traces older than 30 days
deleted = asyncio.run(monitor._storage.purge(older_than=timedelta(days=30)))
print(f"Purged {deleted} old traces")
```

## GDPR posture

- All data is **on-machine by default**
- Export only happens on explicit user action (`monitor.export(...)`)
- `store_prompts=False` mode stores no personal content
- `purge()` API allows right-to-erasure workflows

## Network exports

If you configure an exporter that sends data over the network (OTEL, LangSmith, MLflow, webhooks), you are responsible for the security of that transport and destination. Keeto uses standard TLS for all outbound HTTP.

## Reporting vulnerabilities

Report security issues privately via GitHub's [private vulnerability reporting](https://github.com/keeto-dev/keeto/security/advisories/new). Do not open public issues for security vulnerabilities.

See [SECURITY.md](https://github.com/keeto-dev/keeto/blob/main/SECURITY.md) in the repository for the full disclosure policy.
