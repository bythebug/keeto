"""LangSmith compatibility adapter — issues #83 (export) and #89 (import).

Export Keeto traces to LangSmith, or import LangSmith runs as Keeto Traces
for side-by-side comparison.

Export (requires ``langsmith`` package or writes a JSON file):

    monitor.export(format="langsmith", project_name="my-project")
    monitor.export(format="langsmith", path="runs.json")   # offline JSON

Import:

    traces = monitor.import_langsmith("my-project", limit=50)
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from keeto.core.span import Span, SpanKind, SpanStatus, Trace

# ---------------------------------------------------------------------------
# Keeto → LangSmith
# ---------------------------------------------------------------------------

_SPAN_KIND_TO_RUN_TYPE: dict[SpanKind, str] = {
    SpanKind.LLM: "llm",
    SpanKind.TOOL: "tool",
    SpanKind.EMBEDDING: "llm",
    SpanKind.CHAIN: "chain",
    SpanKind.AGENT: "chain",
    SpanKind.RETRIEVAL: "retriever",
    SpanKind.CUSTOM: "chain",
}


def _span_to_run(span: Span, project_name: str) -> dict[str, Any]:
    run_type = _SPAN_KIND_TO_RUN_TYPE.get(span.kind, "chain")
    inputs: dict[str, Any] = {}
    outputs: dict[str, Any] = {}

    if "llm.messages" in span.attributes:
        inputs["messages"] = span.attributes["llm.messages"]
    if "llm.system_prompt" in span.attributes:
        inputs["system"] = span.attributes["llm.system_prompt"]
    if "llm.response" in span.attributes:
        outputs["output"] = span.attributes["llm.response"]
    if "tool.input" in span.attributes:
        inputs["input"] = span.attributes["tool.input"]
    if "tool.output" in span.attributes:
        outputs["output"] = span.attributes["tool.output"]

    extra: dict[str, Any] = {}
    if span.model:
        extra["model_name"] = span.model
    if span.input_tokens is not None or span.output_tokens is not None:
        extra["usage"] = {
            "prompt_tokens": span.input_tokens or 0,
            "completion_tokens": span.output_tokens or 0,
            "total_tokens": (span.input_tokens or 0) + (span.output_tokens or 0),
        }

    run: dict[str, Any] = {
        "id": str(uuid.UUID(span.span_id.ljust(32, "0")[:32])),
        "name": span.name,
        "run_type": run_type,
        "inputs": inputs,
        "outputs": outputs,
        "start_time": span.start_time.isoformat(),
        "end_time": span.end_time.isoformat() if span.end_time else None,
        "error": span.status_message if span.status == SpanStatus.ERROR else None,
        "extra": extra,
        "tags": [f"provider:{span.provider}"] if span.provider else [],
        "session_name": project_name,
    }
    if span.parent_span_id:
        run["parent_run_id"] = str(uuid.UUID(span.parent_span_id.ljust(32, "0")[:32]))
    return run


def export_langsmith(
    traces: list[Trace],
    path: str | None = None,
    project_name: str = "keeto",
    api_key: str | None = None,
    api_url: str | None = None,
) -> None:
    """Export traces to LangSmith (or to a JSON file if *path* is given).

    When *path* is provided the runs are written as JSON — no ``langsmith``
    package required.  Without *path*, the ``langsmith`` package must be
    installed and ``LANGCHAIN_API_KEY`` must be set (or pass *api_key*).
    """
    runs = [_span_to_run(span, project_name) for trace in traces for span in trace.spans]

    if path:
        payload = json.dumps(runs, indent=2, default=str)
        if path == "-":
            sys.stdout.write(payload)
            sys.stdout.write("\n")
        else:
            Path(path).write_text(payload, encoding="utf-8")
        return

    if not runs:
        return

    try:
        import langsmith  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("LangSmith upload requires the langsmith package. Install: pip install langsmith") from exc

    key = api_key or os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
    client = langsmith.Client(api_key=key, api_url=api_url)
    for run in runs:
        client.create_run(**run)


# ---------------------------------------------------------------------------
# LangSmith → Keeto
# ---------------------------------------------------------------------------


def _run_to_span(run: Any) -> Span:
    """Convert a LangSmith run (dict or Run object) to a Keeto Span."""
    if not isinstance(run, dict):
        run = run.__dict__ if hasattr(run, "__dict__") else dict(run)

    def _dt(val: Any) -> datetime:
        if val is None:
            return datetime.now(UTC)
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=UTC)
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))

    run_type = run.get("run_type", "chain")
    kind_map = {
        "llm": SpanKind.LLM,
        "tool": SpanKind.TOOL,
        "chain": SpanKind.CHAIN,
        "retriever": SpanKind.RETRIEVAL,
    }
    kind = kind_map.get(run_type, SpanKind.CUSTOM)

    raw_id = str(run.get("id", uuid.uuid4()))
    span_id = raw_id.replace("-", "")[:16]
    trace_id = str(run.get("trace_id") or raw_id).replace("-", "")[:32]

    parent_raw = run.get("parent_run_id")
    parent_span_id = str(parent_raw).replace("-", "")[:16] if parent_raw else None

    error = run.get("error")
    status = SpanStatus.ERROR if error else SpanStatus.OK

    extra = run.get("extra") or {}
    usage = extra.get("usage") or {}

    attrs: dict[str, Any] = {}
    inputs = run.get("inputs") or {}
    outputs = run.get("outputs") or {}
    if inputs:
        attrs["llm.messages"] = inputs.get("messages", inputs)
    if "system" in inputs:
        attrs["llm.system_prompt"] = inputs["system"]
    if outputs:
        attrs["llm.response"] = outputs.get("output", outputs)

    span = Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=run.get("name", "langsmith.run"),
        kind=kind,
        start_time=_dt(run.get("start_time")),
        end_time=_dt(run.get("end_time")) if run.get("end_time") else None,
        status=status,
        status_message=error,
        provider="langsmith",
        model=extra.get("model_name") or extra.get("invocation_params", {}).get("model_name"),
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        attributes=attrs,
    )
    return span


def import_from_langsmith(
    project_name: str,
    limit: int = 100,
    api_key: str | None = None,
    api_url: str | None = None,
) -> list[Trace]:
    """Fetch runs from a LangSmith project and return them as Keeto Traces.

    Requires the ``langsmith`` package and a valid API key.
    """
    try:
        import langsmith  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("LangSmith import requires the langsmith package. Install: pip install langsmith") from exc

    key = api_key or os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
    client = langsmith.Client(api_key=key, api_url=api_url)
    runs = list(client.list_runs(project_name=project_name, limit=limit))

    # Group by trace_id
    trace_map: dict[str, Trace] = {}
    for run in runs:
        span = _run_to_span(run)
        if span.trace_id not in trace_map:
            trace_map[span.trace_id] = Trace(trace_id=span.trace_id, start_time=span.start_time)
        trace_map[span.trace_id].add_span(span)

    return list(trace_map.values())
