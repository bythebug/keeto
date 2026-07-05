"""Tests for MLflow compatibility adapter — issue #84."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from keeto.core.span import Span, SpanKind, SpanStatus, Trace
from keeto.exporters.mlflow import export_mlflow


def _make_trace(
    provider: str = "openai",
    model: str = "gpt-4o",
    input_tokens: int = 200,
    output_tokens: int = 60,
    cost_usd: float = 0.002,
    error: bool = False,
) -> Trace:
    now = datetime.now(timezone.utc)
    span = Span(
        trace_id="a" * 32,
        span_id="b" * 16,
        name="openai.chat",
        kind=SpanKind.LLM,
        start_time=now,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    span.finish(
        status=SpanStatus.ERROR if error else SpanStatus.OK,
        end_time=now + timedelta(milliseconds=800),
    )
    trace = Trace(trace_id="a" * 32, start_time=now)
    trace.add_span(span)
    return trace


def _mlflow_mock() -> MagicMock:
    """mlflow mock with context-manager start_run."""
    mock = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    mock.start_run.return_value = cm
    return mock


class TestExportMlflow:
    def test_raises_without_mlflow(self) -> None:
        with patch.dict("sys.modules", {"mlflow": None}):  # type: ignore[dict-item]
            with pytest.raises(ImportError, match="mlflow"):
                export_mlflow([_make_trace()])

    def test_sets_experiment(self) -> None:
        mock = _mlflow_mock()
        with patch.dict("sys.modules", {"mlflow": mock}):
            export_mlflow([_make_trace()], experiment_name="test-exp")
        mock.set_experiment.assert_called_once_with("test-exp")

    def test_sets_tracking_uri(self) -> None:
        mock = _mlflow_mock()
        with patch.dict("sys.modules", {"mlflow": mock}):
            export_mlflow([_make_trace()], tracking_uri="http://mlflow:5000")
        mock.set_tracking_uri.assert_called_once_with("http://mlflow:5000")

    def test_no_tracking_uri_not_called(self) -> None:
        mock = _mlflow_mock()
        with patch.dict("sys.modules", {"mlflow": mock}):
            export_mlflow([_make_trace()])
        mock.set_tracking_uri.assert_not_called()

    def test_logs_metrics(self) -> None:
        mock = _mlflow_mock()
        logged: dict[str, float] = {}
        mock.log_metric.side_effect = lambda k, v: logged.update({k: v})

        with patch.dict("sys.modules", {"mlflow": mock}):
            export_mlflow([_make_trace(input_tokens=300, output_tokens=90, cost_usd=0.005)])

        assert logged.get("input_tokens") == 300.0
        assert "output_tokens" in logged
        assert "cost_usd" in logged
        assert "latency_ms" in logged

    def test_sets_provider_tag(self) -> None:
        mock = _mlflow_mock()
        tags: dict[str, str] = {}
        mock.set_tag.side_effect = lambda k, v: tags.update({k: str(v)})

        with patch.dict("sys.modules", {"mlflow": mock}):
            export_mlflow([_make_trace(provider="anthropic", model="claude-3-5")])

        assert tags.get("gen_ai.system") == "anthropic"
        assert tags.get("gen_ai.request.model") == "claude-3-5"

    def test_error_status_tag(self) -> None:
        mock = _mlflow_mock()
        tags: dict[str, str] = {}
        mock.set_tag.side_effect = lambda k, v: tags.update({k: str(v)})

        with patch.dict("sys.modules", {"mlflow": mock}):
            export_mlflow([_make_trace(error=True)])

        assert tags.get("status") == "error"

    def test_empty_traces_no_op(self) -> None:
        mock = _mlflow_mock()
        with patch.dict("sys.modules", {"mlflow": mock}):
            export_mlflow([])
        mock.start_run.assert_not_called()
