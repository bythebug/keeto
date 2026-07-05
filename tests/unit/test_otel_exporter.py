"""Tests for OTEL OTLP exporter — issues #81, #82."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from keeto.core.span import Span, SpanKind, SpanStatus, Trace
from keeto.exporters.otel import _ns, _span_id_int, _trace_id_int, export_otel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace(
    trace_id: str = "a" * 32,
    span_id: str = "b" * 16,
    provider: str = "openai",
    model: str = "gpt-4o",
    error: bool = False,
) -> Trace:
    now = datetime.now(UTC)
    span = Span(
        trace_id=trace_id,
        span_id=span_id,
        name="openai.chat",
        kind=SpanKind.LLM,
        start_time=now,
        provider=provider,
        model=model,
        input_tokens=200,
        output_tokens=50,
        cost_usd=0.001,
    )
    span.finish(
        status=SpanStatus.ERROR if error else SpanStatus.OK,
        end_time=now + timedelta(milliseconds=500),
    )
    trace = Trace(trace_id=trace_id, start_time=now)
    trace.add_span(span)
    return trace


def _make_otel_mocks() -> dict[str, MagicMock]:
    """Build a minimal sys.modules stub for the OTel SDK."""
    StatusCode = MagicMock()
    StatusCode.OK = "OK"
    StatusCode.ERROR = "ERROR"
    StatusCode.UNSET = "UNSET"

    Status = MagicMock(side_effect=lambda code, msg="": MagicMock(_code=code, _msg=msg))

    TraceFlags = MagicMock()
    TraceFlags.SAMPLED = 1
    TraceFlags.side_effect = lambda x: x

    SpanContext = MagicMock(side_effect=lambda **kw: MagicMock(**kw))

    OtelSpanKind = MagicMock()
    OtelSpanKind.INTERNAL = "INTERNAL"

    mock_trace = MagicMock()
    mock_trace.SpanContext = SpanContext
    mock_trace.SpanKind = OtelSpanKind
    mock_trace.TraceFlags = TraceFlags

    mock_trace_status = MagicMock()
    mock_trace_status.Status = Status
    mock_trace_status.StatusCode = StatusCode

    ReadableSpan = MagicMock()
    mock_sdk_trace = MagicMock()
    mock_sdk_trace.ReadableSpan = ReadableSpan

    InstrumentationScope = MagicMock()
    mock_instrumentation = MagicMock()
    mock_instrumentation.InstrumentationScope = InstrumentationScope

    Resource = MagicMock()
    Resource.create = MagicMock(return_value=MagicMock())
    SERVICE_NAME = "service.name"
    mock_resources = MagicMock()
    mock_resources.Resource = Resource
    mock_resources.SERVICE_NAME = SERVICE_NAME

    SpanExportResult = MagicMock()
    SpanExportResult.SUCCESS = "SUCCESS"
    mock_export = MagicMock()
    mock_export.SpanExportResult = SpanExportResult

    OTLPSpanExporter = MagicMock()
    OTLPSpanExporter.return_value.export.return_value = SpanExportResult.SUCCESS
    mock_grpc = MagicMock()
    mock_grpc.OTLPSpanExporter = OTLPSpanExporter

    return {
        "opentelemetry.sdk.trace": mock_sdk_trace,
        "opentelemetry.sdk.instrumentation": mock_instrumentation,
        "opentelemetry.trace": mock_trace,
        "opentelemetry.trace.status": mock_trace_status,
        "opentelemetry.sdk.resources": mock_resources,
        "opentelemetry.sdk.trace.export": mock_export,
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": mock_grpc,
        "opentelemetry": MagicMock(),
        "opentelemetry.sdk": MagicMock(),
        "opentelemetry.exporter": MagicMock(),
        "opentelemetry.exporter.otlp": MagicMock(),
        "opentelemetry.exporter.otlp.proto": MagicMock(),
        "opentelemetry.exporter.otlp.proto.grpc": MagicMock(),
    }


# ---------------------------------------------------------------------------
# ID conversion helpers
# ---------------------------------------------------------------------------


class TestIdConversions:
    def test_trace_id_int_roundtrip(self) -> None:
        tid = "a" * 32
        assert _trace_id_int(tid) == int(tid, 16)

    def test_span_id_int_roundtrip(self) -> None:
        sid = "b" * 16
        assert _span_id_int(sid) == int(sid, 16)

    def test_short_trace_id_padded(self) -> None:
        result = _trace_id_int("abc")
        assert result == int("abc" + "0" * 29, 16)

    def test_ns_conversion(self) -> None:
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert _ns(dt) == int(dt.timestamp() * 1_000_000_000)


# ---------------------------------------------------------------------------
# _to_otel_span — attribute mapping
# ---------------------------------------------------------------------------


class TestToOtelSpan:
    def test_attributes_mapped(self) -> None:
        from keeto.exporters.otel import _to_otel_span

        trace = _make_trace()
        span = trace.spans[0]
        mock_resource = MagicMock()

        mocks = _make_otel_mocks()
        with patch.dict("sys.modules", mocks):
            _to_otel_span(span, mock_resource)

        ReadableSpan = mocks["opentelemetry.sdk.trace"].ReadableSpan
        assert ReadableSpan.called
        call_kwargs = ReadableSpan.call_args[1]
        attrs = call_kwargs["attributes"]
        assert attrs["gen_ai.system"] == "openai"
        assert attrs["gen_ai.request.model"] == "gpt-4o"
        assert attrs["gen_ai.usage.input_tokens"] == 200
        assert attrs["gen_ai.usage.output_tokens"] == 50

    def test_no_provider_or_model_omitted(self) -> None:
        from keeto.exporters.otel import _to_otel_span

        now = datetime.now(UTC)
        span = Span(trace_id="a" * 32, span_id="b" * 16, name="custom", kind=SpanKind.CUSTOM, start_time=now)
        span.finish()
        mock_resource = MagicMock()

        mocks = _make_otel_mocks()
        with patch.dict("sys.modules", mocks):
            _to_otel_span(span, mock_resource)

        ReadableSpan = mocks["opentelemetry.sdk.trace"].ReadableSpan
        attrs = ReadableSpan.call_args[1]["attributes"]
        assert "gen_ai.system" not in attrs
        assert "gen_ai.request.model" not in attrs

    def test_parent_span_set_when_parent_id_present(self) -> None:
        from keeto.exporters.otel import _to_otel_span

        now = datetime.now(UTC)
        span = Span(
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id="c" * 16,
            name="child",
            kind=SpanKind.LLM,
            start_time=now,
        )
        span.finish()
        mock_resource = MagicMock()

        mocks = _make_otel_mocks()
        with patch.dict("sys.modules", mocks):
            _to_otel_span(span, mock_resource)

        ReadableSpan = mocks["opentelemetry.sdk.trace"].ReadableSpan
        call_kwargs = ReadableSpan.call_args[1]
        assert call_kwargs["parent"] is not None


# ---------------------------------------------------------------------------
# export_otel — error handling
# ---------------------------------------------------------------------------


class TestExportOtel:
    def test_raises_when_otel_not_installed(self) -> None:
        mods = {"opentelemetry.sdk.resources": None}
        with patch.dict("sys.modules", mods), pytest.raises(ImportError, match="keeto\\[otel\\]"):  # type: ignore[dict-item]
            export_otel([_make_trace()])

    def test_unknown_protocol_raises(self) -> None:
        mocks = _make_otel_mocks()
        with patch.dict("sys.modules", mocks), pytest.raises(ValueError, match="Unknown OTLP protocol"):
            export_otel([_make_trace()], protocol="invalid")

    def test_empty_traces_no_op(self) -> None:
        mocks = _make_otel_mocks()
        with patch.dict("sys.modules", mocks):
            export_otel([])
        # No exporter should be created for empty input
        grpc_exporter = mocks["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"].OTLPSpanExporter
        grpc_exporter.assert_not_called()

    def test_grpc_export_called(self) -> None:
        mocks = _make_otel_mocks()
        grpc_exporter_inst = MagicMock()
        grpc_exporter_inst.export.return_value = mocks["opentelemetry.sdk.trace.export"].SpanExportResult.SUCCESS
        otlp_cls = mocks["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"].OTLPSpanExporter
        otlp_cls.return_value = grpc_exporter_inst

        with patch.dict("sys.modules", mocks):
            export_otel([_make_trace()], endpoint="http://localhost:4317", protocol="grpc")

        grpc_exporter_inst.export.assert_called_once()
        grpc_exporter_inst.shutdown.assert_called_once()
