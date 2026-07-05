"""Tests for LangSmith adapter — issues #83 (export) and #89 (import)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from keeto.core.span import Span, SpanKind, SpanStatus, Trace
from keeto.exporters.langsmith import (
    _run_to_span,
    _span_to_run,
    export_langsmith,
    import_from_langsmith,
)


def _make_trace() -> Trace:
    now = datetime.now(UTC)
    span = Span(
        trace_id="a" * 32,
        span_id="b" * 16,
        name="openai.chat",
        kind=SpanKind.LLM,
        start_time=now,
        provider="openai",
        model="gpt-4o",
        input_tokens=200,
        output_tokens=50,
        cost_usd=0.001,
        attributes={"llm.messages": [{"role": "user", "content": "hello"}]},
    )
    span.finish(status=SpanStatus.OK)
    trace = Trace(trace_id="a" * 32, start_time=now)
    trace.add_span(span)
    return trace


class TestSpanToRun:
    def test_run_type_llm(self) -> None:
        run = _span_to_run(_make_trace().spans[0], "keeto")
        assert run["run_type"] == "llm"

    def test_messages_in_inputs(self) -> None:
        run = _span_to_run(_make_trace().spans[0], "keeto")
        assert "messages" in run["inputs"]

    def test_model_in_extra(self) -> None:
        run = _span_to_run(_make_trace().spans[0], "keeto")
        assert run["extra"]["model_name"] == "gpt-4o"

    def test_token_usage_in_extra(self) -> None:
        run = _span_to_run(_make_trace().spans[0], "keeto")
        usage = run["extra"]["usage"]
        assert usage["prompt_tokens"] == 200
        assert usage["completion_tokens"] == 50

    def test_error_mapped(self) -> None:
        now = datetime.now(UTC)
        span = Span(trace_id="a" * 32, span_id="b" * 16, name="test", kind=SpanKind.LLM, start_time=now)
        span.finish(status=SpanStatus.ERROR, status_message="timeout")
        assert _span_to_run(span, "keeto")["error"] == "timeout"

    def test_ok_error_is_none(self) -> None:
        run = _span_to_run(_make_trace().spans[0], "keeto")
        assert run["error"] is None

    def test_project_name_in_session(self) -> None:
        run = _span_to_run(_make_trace().spans[0], "my-project")
        assert run["session_name"] == "my-project"

    def test_tool_run_type(self) -> None:
        now = datetime.now(UTC)
        span = Span(trace_id="a" * 32, span_id="b" * 16, name="search", kind=SpanKind.TOOL, start_time=now)
        span.finish()
        assert _span_to_run(span, "keeto")["run_type"] == "tool"

    def test_retrieval_run_type(self) -> None:
        now = datetime.now(UTC)
        span = Span(trace_id="a" * 32, span_id="b" * 16, name="retrieve", kind=SpanKind.RETRIEVAL, start_time=now)
        span.finish()
        assert _span_to_run(span, "keeto")["run_type"] == "retriever"


class TestRunToSpan:
    def _sample_run(self) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            "name": "ChatOpenAI",
            "run_type": "llm",
            "inputs": {"messages": [{"role": "user", "content": "hi"}]},
            "outputs": {"output": "Hello!"},
            "start_time": datetime.now(UTC).isoformat(),
            "end_time": None,
            "error": None,
            "extra": {
                "model_name": "gpt-3.5-turbo",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
            "parent_run_id": None,
        }

    def test_kind_is_llm(self) -> None:
        assert _run_to_span(self._sample_run()).kind == SpanKind.LLM

    def test_model_populated(self) -> None:
        assert _run_to_span(self._sample_run()).model == "gpt-3.5-turbo"

    def test_token_counts(self) -> None:
        span = _run_to_span(self._sample_run())
        assert span.input_tokens == 10
        assert span.output_tokens == 5

    def test_ok_status_when_no_error(self) -> None:
        assert _run_to_span(self._sample_run()).status == SpanStatus.OK

    def test_error_status(self) -> None:
        run = self._sample_run()
        run["error"] = "rate limit"
        span = _run_to_span(run)
        assert span.status == SpanStatus.ERROR
        assert span.status_message == "rate limit"

    def test_chain_kind(self) -> None:
        run = self._sample_run()
        run["run_type"] = "chain"
        assert _run_to_span(run).kind == SpanKind.CHAIN


class TestExportLangsmithJson:
    def test_writes_json_file(self, tmp_path: Path) -> None:
        out = str(tmp_path / "runs.json")
        export_langsmith([_make_trace()], path=out, project_name="test")
        data = json.loads(Path(out).read_text())
        assert len(data) == 1
        assert data[0]["run_type"] == "llm"

    def test_empty_traces_writes_empty_json(self, tmp_path: Path) -> None:
        out = str(tmp_path / "empty.json")
        export_langsmith([], path=out)
        data = json.loads(Path(out).read_text())
        assert data == []

    def test_no_langsmith_package_raises(self) -> None:
        # No path → tries API upload → needs langsmith package
        with patch.dict("sys.modules", {"langsmith": None}), pytest.raises(ImportError, match="langsmith"):  # type: ignore[dict-item]
            export_langsmith([_make_trace()])


class TestImportFromLangsmith:
    def test_import_returns_traces(self) -> None:
        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        mock_run = {
            "id": run_id,
            "trace_id": trace_id,
            "name": "test",
            "run_type": "llm",
            "inputs": {},
            "outputs": {},
            "start_time": datetime.now(UTC).isoformat(),
            "end_time": None,
            "error": None,
            "extra": {},
            "parent_run_id": None,
        }
        mock_client = MagicMock()
        mock_client.list_runs.return_value = [mock_run]
        mock_langsmith = MagicMock()
        mock_langsmith.Client.return_value = mock_client

        with patch.dict("sys.modules", {"langsmith": mock_langsmith}):
            traces = import_from_langsmith("my-project", limit=10)

        assert len(traces) >= 1
        assert all(isinstance(t, Trace) for t in traces)

    def test_groups_spans_by_trace_id(self) -> None:
        trace_id = str(uuid.uuid4())
        runs = [
            {
                "id": str(uuid.uuid4()),
                "trace_id": trace_id,
                "name": f"run{i}",
                "run_type": "llm",
                "inputs": {},
                "outputs": {},
                "start_time": datetime.now(UTC).isoformat(),
                "end_time": None,
                "error": None,
                "extra": {},
                "parent_run_id": None,
            }
            for i in range(3)
        ]
        mock_client = MagicMock()
        mock_client.list_runs.return_value = runs
        mock_langsmith = MagicMock()
        mock_langsmith.Client.return_value = mock_client

        with patch.dict("sys.modules", {"langsmith": mock_langsmith}):
            traces = import_from_langsmith("my-project", limit=10)

        # All 3 runs have the same trace_id, so they should be in 1 trace
        assert len(traces) == 1
        assert len(traces[0].spans) == 3

    def test_import_requires_langsmith_package(self) -> None:
        with patch.dict("sys.modules", {"langsmith": None}), pytest.raises(ImportError, match="langsmith"):  # type: ignore[dict-item]
            import_from_langsmith("project")
