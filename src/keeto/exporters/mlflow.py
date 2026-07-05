"""MLflow compatibility adapter — issue #84.

Logs Keeto traces as MLflow runs so they appear in the MLflow Tracking UI
alongside model experiments.

Usage::

    monitor.export(format="mlflow", experiment_name="my-experiment")
    monitor.export(format="mlflow", tracking_uri="http://mlflow:5000")
"""

from __future__ import annotations

from typing import Any

from keeto.core.span import SpanStatus, Trace


def export_mlflow(
    traces: list[Trace],
    experiment_name: str = "keeto",
    tracking_uri: str | None = None,
    run_name_prefix: str = "keeto",
) -> None:
    """Log traces as MLflow runs.

    Each Keeto trace becomes one MLflow run.  Span-level detail is stored as
    nested child runs when the trace has multiple spans.

    Requires the ``mlflow`` package::

        pip install mlflow
    """
    try:
        import mlflow  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "MLflow export requires the mlflow package. Install: pip install mlflow"
        ) from exc

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    mlflow.set_experiment(experiment_name)

    for trace in traces:
        _log_trace(mlflow, trace, run_name_prefix)


def _log_trace(mlflow: Any, trace: Trace, run_name_prefix: str) -> None:
    root = trace.root_span
    run_name = f"{run_name_prefix}/{root.name}" if root else f"{run_name_prefix}/{trace.trace_id[:8]}"

    with mlflow.start_run(run_name=run_name):
        mlflow.set_tag("keeto.trace_id", trace.trace_id)

        if root:
            if root.provider:
                mlflow.set_tag("gen_ai.system", root.provider)
            if root.model:
                mlflow.set_tag("gen_ai.request.model", root.model)
            if root.status == SpanStatus.ERROR:
                mlflow.set_tag("status", "error")
                if root.status_message:
                    mlflow.set_tag("error.message", root.status_message)
            else:
                mlflow.set_tag("status", root.status.value)

        # Aggregate metrics from all spans
        total_input = sum(s.input_tokens or 0 for s in trace.spans)
        total_output = sum(s.output_tokens or 0 for s in trace.spans)
        total_cost = trace.total_cost_usd
        latency = trace.latency_ms

        if total_input:
            mlflow.log_metric("input_tokens", total_input)
        if total_output:
            mlflow.log_metric("output_tokens", total_output)
        if total_cost:
            mlflow.log_metric("cost_usd", total_cost)
        if latency is not None:
            mlflow.log_metric("latency_ms", latency)

        # Log each span as a child run when there are multiple spans
        if len(trace.spans) > 1:
            for span in trace.spans:
                with mlflow.start_run(
                    run_name=span.name,
                    nested=True,
                ):
                    mlflow.set_tag("keeto.span_id", span.span_id)
                    mlflow.set_tag("keeto.span_kind", span.kind.value)
                    if span.model:
                        mlflow.set_tag("gen_ai.request.model", span.model)
                    if span.input_tokens is not None:
                        mlflow.log_metric("input_tokens", span.input_tokens)
                    if span.output_tokens is not None:
                        mlflow.log_metric("output_tokens", span.output_tokens)
                    if span.cost_usd is not None:
                        mlflow.log_metric("cost_usd", span.cost_usd)
                    if span.latency_ms is not None:
                        mlflow.log_metric("latency_ms", span.latency_ms)
                    for k, v in span.attributes.items():
                        if isinstance(v, (int, float)):
                            mlflow.log_metric(k, v)
                        elif isinstance(v, (str, bool)):
                            mlflow.set_tag(k, str(v))
