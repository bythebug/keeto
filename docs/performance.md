# Performance

## Overhead target

Keeto targets **<5% latency overhead** on AI calls. In practice, overhead is typically **<1ms** because AI calls themselves take 500ms–30s.

## Benchmark results

```
Baseline (100 mock AI calls, no Keeto):  847ms total, 8.5ms avg
With Keeto (same calls):                 849ms total, 8.5ms avg
Overhead:                                +2ms total, +0.02ms avg (0.2%)
```

Run benchmarks yourself:

```bash
make benchmark
```

CI enforces <5% overhead on every PR.

## How overhead is minimized

### Non-blocking hot path

The interceptor records only two timestamps and enqueues a lightweight `PendingSpan` object. No JSON parsing, no database writes, no analysis happens on the calling thread.

```
AI SDK call starts
    │
    ▼
httpx transport (patched)       ← records start_time, enqueues span
    │
    ▼  (returns immediately)
AI SDK call ends
    │
    ▼
asyncio.Queue (non-blocking)    ← ~1μs enqueue
    │
    ▼  (background daemon thread)
Worker: parse → enrich → store → analyze
```

### Lock-free queue

`asyncio.Queue` (async apps) or `queue.SimpleQueue` (sync apps via a dedicated event loop on a daemon thread). The caller never blocks waiting for storage writes.

### Batch flush

Events accumulate in the worker and flush every 50ms or 100 events — whichever comes first. One storage write per batch instead of one per event.

### Lazy deserialization

Raw response bytes are stored. JSON parsing only happens when queried by the dashboard or analyzer — never on the hot path.

### Background daemon thread

All processing runs on a daemon thread. It dies silently when the process exits. Crashes in the worker are caught, logged, and swallowed — they never affect the main application.

## Sampling

For very high-throughput applications:

```python
monitor = Monitor(sample_rate=0.01)  # capture 1% of requests
```

Errors are always captured regardless of `sample_rate`.

## Memory bounds

`MemoryStorage` uses a ring buffer — it never grows beyond `max_size` traces (default: 1000). For long-running services, use `SQLiteStorage` or set a short auto-purge:

```python
from datetime import timedelta
asyncio.run(monitor._storage.purge(older_than=timedelta(hours=24)))
```

## SQLite write latency

SQLite writes are async (via `aiosqlite`) and non-blocking. A typical span write takes **<1ms** and is batched with other writes.

## Disabling Keeto entirely

```python
import os
os.environ["KEETO_DISABLED"] = "1"
```

When set, `monitor.start()` is a no-op. Use this in environments where even the minimal overhead is unacceptable (unlikely given AI call latencies).
