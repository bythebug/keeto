"""Tests for JSON and CSV exporters (#19 and #40)."""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from pathlib import Path

import pytest

from keeto.core.span import Span, SpanStatus, Trace
from keeto.exporters.csv import export_csv
from keeto.exporters.json import export_json


def _make_trace(
    trace_id: str = "abc123",
    provider: str = "openai",
    model: str = "gpt-4o",
    latency_ms: float = 500.0,
    input_tokens: int = 200,
    output_tokens: int = 80,
    cost_usd: float = 0.0012,
    error: bool = False,
) -> Trace:
    trace = Trace(trace_id=trace_id)
    span = Span(
        trace_id=trace_id,
        span_id="s1",
        name=f"{provider}.chat",
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    span.finish(status=SpanStatus.ERROR if error else SpanStatus.OK)
    span.end_time = span.start_time + timedelta(milliseconds=latency_ms)
    trace.add_span(span)
    return trace


# ---------------------------------------------------------------------------
# JSON exporter
# ---------------------------------------------------------------------------


class TestExportJson:
    def test_stdout_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        traces = [_make_trace("t1"), _make_trace("t2")]
        export_json(traces)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 2

    def test_writes_file(self, tmp_path: Path) -> None:
        traces = [_make_trace("t1")]
        out_file = str(tmp_path / "out.json")
        export_json(traces, path=out_file)
        data = json.loads(Path(out_file).read_text())
        assert len(data) == 1
        assert data[0]["trace_id"] == "t1"

    def test_empty_traces(self, tmp_path: Path) -> None:
        out_file = str(tmp_path / "empty.json")
        export_json([], path=out_file)
        data = json.loads(Path(out_file).read_text())
        assert data == []

    def test_fields_present(self, tmp_path: Path) -> None:
        traces = [_make_trace("t1", provider="anthropic", model="claude-3-5-sonnet")]
        out_file = str(tmp_path / "out.json")
        export_json(traces, path=out_file)
        data = json.loads(Path(out_file).read_text())
        record = data[0]
        assert record["trace_id"] == "t1"
        assert "spans" in record
        assert record["spans"][0]["provider"] == "anthropic"
        assert record["spans"][0]["model"] == "claude-3-5-sonnet"


# ---------------------------------------------------------------------------
# CSV exporter
# ---------------------------------------------------------------------------


class TestExportCsv:
    def test_stdout_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        traces = [_make_trace("t1"), _make_trace("t2")]
        export_csv(traces)
        out = capsys.readouterr().out
        reader = csv.DictReader(io.StringIO(out))
        rows = list(reader)
        assert len(rows) == 2

    def test_writes_file(self, tmp_path: Path) -> None:
        traces = [_make_trace("t1")]
        out_file = str(tmp_path / "out.csv")
        export_csv(traces, path=out_file)
        with Path(out_file).open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["trace_id"] == "t1"

    def test_header_fields(self, tmp_path: Path) -> None:
        from keeto.exporters.csv import _FIELDS

        out_file = str(tmp_path / "out.csv")
        export_csv([_make_trace("t1")], path=out_file)
        with Path(out_file).open() as f:
            reader = csv.DictReader(f)
            assert set(reader.fieldnames or []) == set(_FIELDS)

    def test_cost_and_tokens(self, tmp_path: Path) -> None:
        traces = [_make_trace("t1", input_tokens=300, output_tokens=90, cost_usd=0.005)]
        out_file = str(tmp_path / "out.csv")
        export_csv(traces, path=out_file)
        with Path(out_file).open() as f:
            row = next(iter(csv.DictReader(f)))
        assert float(row["cost_usd"]) == pytest.approx(0.005)
        assert int(row["input_tokens"]) == 300
        assert int(row["output_tokens"]) == 90

    def test_error_flag(self, tmp_path: Path) -> None:
        traces = [_make_trace("t1", error=True)]
        out_file = str(tmp_path / "out.csv")
        export_csv(traces, path=out_file)
        with Path(out_file).open() as f:
            row = next(iter(csv.DictReader(f)))
        assert row["has_error"] == "True"

    def test_empty_traces(self, tmp_path: Path) -> None:
        out_file = str(tmp_path / "out.csv")
        export_csv([], path=out_file)
        with Path(out_file).open() as f:
            assert list(csv.DictReader(f)) == []

    def test_latency_populated(self, tmp_path: Path) -> None:
        traces = [_make_trace("t1", latency_ms=750.0)]
        out_file = str(tmp_path / "out.csv")
        export_csv(traces, path=out_file)
        with Path(out_file).open() as f:
            row = next(iter(csv.DictReader(f)))
        assert float(row["latency_ms"]) == pytest.approx(750.0)

    def test_multiple_traces_order(self, tmp_path: Path) -> None:
        traces = [_make_trace(f"t{i}") for i in range(5)]
        out_file = str(tmp_path / "out.csv")
        export_csv(traces, path=out_file)
        with Path(out_file).open() as f:
            ids = [r["trace_id"] for r in csv.DictReader(f)]
        assert ids == [f"t{i}" for i in range(5)]
