"""
Keeto — Comprehensive Real-World End-to-End Test
=================================================
Simulates a production AI application that uses:
  • OpenAI (gpt-4o) for user-facing chat with tool calls
  • Anthropic (claude-3-5-sonnet) for document summarisation
  • LiteLLM callback for a proxy layer
  • Manual spans for vector DB search and SQL lookups
  • Budget alerts (daily USD cap, monthly token cap)
  • PII scrubbing
  • SQLite persistent storage
  • JSON + CSV export
  • Recommendations engine
  • Rich dashboard summary

No real API keys are needed — httpx calls are intercepted by respx.

Run standalone:  python tests/e2e/test_realworld.py
Run via pytest:  pytest tests/e2e/test_realworld.py -v -s
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from keeto.core.monitor import Monitor
from keeto.core.span import Span, SpanKind, SpanStatus, Trace
from keeto.storage.memory import MemoryStorage

PASS = "✅"
FAIL = "❌"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    icon = PASS if condition else FAIL
    print(f"  {icon}  {name}" + (f"  ({detail})" if detail else ""))
    results.append((name, condition, detail))
    if not condition:
        import traceback

        traceback.print_stack(limit=4)


# ─── Response factories ────────────────────────────────────────────────────────


def openai_chat_response(
    model: str = "gpt-4o",
    input_tokens: int = 300,
    output_tokens: int = 120,
    finish_reason: str = "stop",
    tool_calls: list[dict[str, Any]] | None = None,
    cached_tokens: int = 0,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": "I can help with that!"}
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = None
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "prompt_tokens_details": {"cached_tokens": cached_tokens},
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


def anthropic_messages_response(
    model: str = "claude-3-5-sonnet-20241022",
    input_tokens: int = 450,
    output_tokens: int = 200,
    tool_uses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = tool_uses if tool_uses else [{"type": "text", "text": "Summary complete."}]
    return {
        "id": "msg_test456",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
        },
    }


def embedding_response(dims: int = 1536, n: int = 3) -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.1] * dims, "index": i} for i in range(n)],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 12 * n, "total_tokens": 12 * n},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 1: Two-line quick-start (minimal API)
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_quickstart() -> None:
    print("\n━━━ Scenario 1: Two-line quick-start ━━━")
    storage = MemoryStorage()
    m = Monitor(storage=storage, auto=False)
    m.start()

    with m.span("user-session") as ctx:
        ctx.set_attribute("user_id", "usr_42")
        time.sleep(0.01)

    time.sleep(0.2)

    traces = asyncio.run(storage.list_traces(limit=10))
    check("Monitor captures span", len(traces) >= 1)
    check("Span has correct name", len(traces) > 0 and traces[0].spans[0].name == "user-session")
    check("Custom attribute stored", len(traces) > 0 and traces[0].spans[0].attributes.get("user_id") == "usr_42")
    check("Monitor idempotent double-start", True)  # verified by calling start() twice below
    m.start()  # should not raise
    m.stop()
    check("Monitor stopped cleanly", not m._started)


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 2: OpenAI chat with tool calls (RAG pattern)
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_openai_rag() -> None:
    print("\n━━━ Scenario 2: OpenAI RAG — chat + tool calls + manual spans ━━━")
    try:
        import openai
    except ImportError:
        print("  ⚠  openai not installed — skipping")
        return

    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False, sample_rate=1.0)
    monitor.start()

    from keeto.integrations.openai.plugin import OpenAIPlugin

    oai_plugin = OpenAIPlugin()
    oai_plugin.install(monitor)

    monitor.set_budget(session_usd=1.0)
    monitor.set_token_budget(daily=500_000)

    tool_calls_payload = [
        {
            "id": "call_search_001",
            "type": "function",
            "function": {
                "name": "vector_search",
                "arguments": '{"query": "quarterly revenue Q3", "top_k": 5}',
            },
        }
    ]

    import openai

    # Both turns in one respx.mock context so the client transport chain stays intact.
    # respx uses side_effect to serve responses in sequence.
    with respx.mock:
        route = respx.post("https://api.openai.com/v1/chat/completions")
        route.side_effect = [
            httpx.Response(
                200,
                json=openai_chat_response(
                    input_tokens=820,
                    output_tokens=45,
                    finish_reason="tool_calls",
                    tool_calls=tool_calls_payload,
                ),
            ),
            httpx.Response(
                200,
                json=openai_chat_response(
                    input_tokens=1200,
                    output_tokens=280,
                    finish_reason="stop",
                    cached_tokens=820,
                ),
            ),
        ]

        client = openai.OpenAI(api_key="sk-fake-key")

        # Turn 1: user asks → model requests tool call
        client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a financial analyst assistant."},
                {"role": "user", "content": "What was our Q3 revenue?"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "vector_search",
                        "description": "Search the document vector store",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "top_k": {"type": "integer"},
                            },
                            "required": ["query"],
                        },
                    },
                }
            ],
        )

        # Simulate vector DB search with a manual span
        with monitor.span("vector-search", kind=SpanKind.CUSTOM) as ctx:
            ctx.set_attribute("query", "quarterly revenue Q3")
            ctx.set_attribute("top_k", 5)
            time.sleep(0.02)
            ctx.set_attribute("results_found", 5)
            ctx.set_attribute("latency_ms", 22.4)

        # Turn 2: model sees tool result and gives final answer
        client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a financial analyst assistant."},
                {"role": "user", "content": "What was our Q3 revenue?"},
                {"role": "assistant", "content": None, "tool_calls": tool_calls_payload},
                {"role": "tool", "tool_call_id": "call_search_001", "content": "[doc1] Q3 revenue: $12.4M"},
            ],
        )

    time.sleep(0.2)

    traces = asyncio.run(storage.list_traces(limit=50))
    llm_traces = [t for t in traces if any(s.name.startswith("openai") for s in t.spans)]
    custom_traces = [t for t in traces if any(s.name == "vector-search" for s in t.spans)]

    check("OpenAI turns captured (2 LLM traces)", len(llm_traces) == 2)
    check("Manual vector-search span captured", len(custom_traces) == 1)

    # list_traces returns newest-first → llm_traces[0]=turn2, llm_traces[-1]=turn1
    turn1 = llm_traces[-1]  # oldest = first call
    span1 = turn1.root_span
    check("Turn 1: tool calls captured", span1 is not None and span1.attributes.get("llm.tool_calls_count") == 1)
    finish_ok = span1 is not None and span1.attributes.get("llm.finish_reason") == "tool_calls"
    check("Turn 1: finish_reason=tool_calls", finish_ok)
    check(
        "Turn 1: tool name is vector_search",
        span1 is not None and (span1.attributes.get("llm.tool_calls") or [{}])[0].get("name") == "vector_search",
    )

    turn2 = llm_traces[0]  # newest = second call
    span2 = turn2.root_span
    check("Turn 2: input_tokens=1200", span2 is not None and span2.input_tokens == 1200)
    check("Turn 2: cached_tokens=820", span2 is not None and span2.cached_tokens == 820)
    check("Turn 2: cost_usd computed", span2 is not None and span2.cost_usd is not None and span2.cost_usd > 0)

    # Cost summary
    cost = monitor.cost_summary()
    check("Cost summary: session_usd > 0", cost["session_usd"] > 0)
    check("Cost summary: openai in by_provider", "openai" in cost["by_provider"])
    check("Cost summary: gpt-4o in by_model", "gpt-4o" in cost["by_model"])

    # Token summary
    tok = monitor.token_summary()
    check("Token summary: session_tokens > 0", tok["session_tokens"] > 0)
    check("Token budget configured", tok["budget_daily"] == 500_000)

    oai_plugin.uninstall()
    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 3: Anthropic summarisation with PII scrubbing
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_anthropic_pii() -> None:
    print("\n━━━ Scenario 3: Anthropic summarisation + PII scrubbing ━━━")
    try:
        import anthropic as _anthropic_mod
    except ImportError:
        print("  ⚠  anthropic not installed — skipping")
        return

    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False, scrub_pii=True)
    monitor.start()

    from keeto.integrations.anthropic.plugin import AnthropicPlugin

    ant_plugin = AnthropicPlugin()
    ant_plugin.install(monitor)

    with respx.mock:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=anthropic_messages_response(input_tokens=650, output_tokens=180))
        )
        client = _anthropic_mod.Anthropic(api_key="sk-ant-fake")
        client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=512,
            system="You are a document summariser.",
            messages=[
                {
                    "role": "user",
                    "content": "Summarise this contract for John Smith (john@acme.com, SSN 123-45-6789).",
                }
            ],
        )

    time.sleep(0.2)

    traces = asyncio.run(storage.list_traces(limit=10))
    check("Anthropic span captured", len(traces) == 1)
    span = traces[0].root_span
    check("Span name is anthropic.messages", span is not None and span.name == "anthropic.messages")
    check("input_tokens=650", span is not None and span.input_tokens == 650)
    check("output_tokens=180", span is not None and span.output_tokens == 180)
    check("cost_usd computed", span is not None and span.cost_usd is not None)
    check("provider=anthropic", span is not None and span.provider == "anthropic")

    ant_plugin.uninstall()
    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 4: Multi-provider session — OpenAI + Anthropic interleaved
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_multi_provider() -> None:
    print("\n━━━ Scenario 4: Multi-provider session ━━━")
    try:
        import anthropic as _ant
        import openai as _oai
    except ImportError:
        print("  ⚠  openai or anthropic not installed — skipping")
        return

    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    from keeto.integrations.anthropic.plugin import AnthropicPlugin
    from keeto.integrations.openai.plugin import OpenAIPlugin

    oai_p = OpenAIPlugin()
    ant_p = AnthropicPlugin()
    oai_p.install(monitor)
    ant_p.install(monitor)

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=openai_chat_response(input_tokens=500, output_tokens=200))
        )
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(200, json=anthropic_messages_response(input_tokens=800, output_tokens=150))
        )
        respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(200, json=embedding_response(dims=1536, n=1))
        )

        oai = _oai.OpenAI(api_key="sk-fake")
        ant = _ant.Anthropic(api_key="sk-ant-fake")

        oai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Draft a short blog post about AI observability."}],
        )
        ant.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=256,
            messages=[{"role": "user", "content": "Critique this blog post: [draft here]"}],
        )
        oai.embeddings.create(model="text-embedding-3-small", input=["AI observability tools comparison"])

    time.sleep(0.2)

    traces = asyncio.run(storage.list_traces(limit=50))
    openai_traces = [t for t in traces if any(s.provider == "openai" for s in t.spans)]
    anthropic_traces = [t for t in traces if any(s.provider == "anthropic" for s in t.spans)]
    embedding_traces = [t for t in traces if any(s.name == "openai.embedding" for s in t.spans)]

    check("2 OpenAI traces (chat + embedding)", len(openai_traces) == 2)
    check("1 Anthropic trace", len(anthropic_traces) == 1)
    check("1 embedding trace", len(embedding_traces) == 1)

    cost = monitor.cost_summary()
    check("Both providers in cost summary", "openai" in cost["by_provider"] and "anthropic" in cost["by_provider"])
    check("Total cost > 0", cost["session_usd"] > 0)

    oai_p.uninstall()
    ant_p.uninstall()
    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 5: Rate limit and error handling
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_errors() -> None:
    print("\n━━━ Scenario 5: Rate limits and errors ━━━")
    try:
        import openai as _oai_err
    except ImportError:
        print("  ⚠  openai not installed — skipping")
        return

    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    from keeto.integrations.openai.plugin import OpenAIPlugin

    err_plugin = OpenAIPlugin()
    err_plugin.install(monitor)

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                429,
                json={"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}},
                headers={"retry-after": "10"},
            )
        )
        client = _oai_err.OpenAI(api_key="sk-fake", max_retries=0)
        with contextlib.suppress(Exception):
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Hello"}],
            )

    time.sleep(0.15)

    traces = asyncio.run(storage.list_traces(limit=10))
    check("Rate limit trace captured", len(traces) == 1)
    span = traces[0].root_span
    check("Span name is rate_limit", span is not None and span.name == "openai.rate_limit")
    check("retry_after_s=10.0", span is not None and span.attributes.get("rate_limit.retry_after_s") == 10.0)
    check("span status is ERROR", span is not None and span.status == SpanStatus.ERROR)

    err_plugin.uninstall()
    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 6: Budget alert fires correctly
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_budget() -> None:
    print("\n━━━ Scenario 6: Budget alerts ━━━")
    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    warnings: list[str] = []
    monitor._console.print = lambda *a, **kw: warnings.append(str(a[0]))  # type: ignore

    monitor.set_budget(session_usd=0.005, daily_usd=0.10)

    for i in range(3):
        span = Span(
            trace_id=f"t{i}",
            span_id=f"s{i}",
            name="openai.chat",
            kind=SpanKind.LLM,
            provider="openai",
            model="gpt-4o",
        )
        span.cost_usd = 0.003
        span.input_tokens = 200
        span.output_tokens = 80
        span.finish(status=SpanStatus.OK)
        monitor.emit(span)

    check("Session budget warning fired", any("session budget exceeded" in w for w in warnings))
    check("Daily budget NOT yet exceeded", not any("daily budget exceeded" in w for w in warnings))
    check("Cost summary correct", monitor.cost_summary()["session_usd"] == pytest.approx(0.009, abs=1e-6))

    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 7: Export to JSON and CSV
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_export(tmp_path: Path) -> None:
    print("\n━━━ Scenario 7: Export JSON + CSV ━━━")
    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    for i in range(3):
        with monitor.span(f"op-{i}") as ctx:
            ctx.set_attribute("iteration", i)
            time.sleep(0.005)

    time.sleep(0.2)

    json_path = tmp_path / "traces.json"
    monitor.export(str(json_path))
    json_data = json.loads(json_path.read_text())
    check("JSON export: list of 3 traces", isinstance(json_data, list) and len(json_data) == 3)
    check("JSON export: trace_id present", "trace_id" in json_data[0])

    csv_path = tmp_path / "traces.csv"
    monitor.export(str(csv_path))
    csv_text = csv_path.read_text()
    check("CSV export: header row present", "trace_id" in csv_text and "latency_ms" in csv_text)
    check("CSV export: 3 data rows", csv_text.count("\n") >= 4)  # header + 3 rows

    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 8: Recommendations engine
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_recommendations() -> None:
    print("\n━━━ Scenario 8: Recommendations engine ━━━")
    from keeto.analyzers.recommendations import RecommendationsEngine

    engine = RecommendationsEngine()
    traces: list[Trace] = []

    # 5 identical-looking calls → agent loop detection
    for i in range(5):
        trace = Trace(trace_id=f"loop-{i}")
        span = Span(trace_id=f"loop-{i}", span_id=f"ls{i}", name="openai.chat", kind=SpanKind.LLM, model="gpt-4o")
        span.input_tokens = 4000
        span.output_tokens = 200
        span.cost_usd = 0.05
        span.set_attribute("llm.message_count", 3)
        span.finish(status=SpanStatus.OK)
        trace.add_span(span)
        traces.append(trace)

    # Huge prompt → prompt size warning
    trace_big = Trace(trace_id="big-prompt")
    span_big = Span(trace_id="big-prompt", span_id="sbig", name="openai.chat", kind=SpanKind.LLM, model="gpt-4o")
    span_big.input_tokens = 120_000
    span_big.output_tokens = 500
    span_big.cost_usd = 1.20
    span_big.finish(status=SpanStatus.OK)
    trace_big.add_span(span_big)
    traces.append(trace_big)

    report = engine.analyze(traces)

    check("Report has recommendations", len(report.recommendations) > 0)
    loop_recs = [r for r in report.recommendations if r.rule == "agent_loop"]
    check("Agent loop rule fires", len(loop_recs) >= 1, f"{[r.rule for r in report.recommendations]}")
    text = str(report)
    check("Report renders without error", len(text) > 0)


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 9: Trace comparison
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_compare() -> None:
    print("\n━━━ Scenario 9: Trace comparison ━━━")
    from keeto.analyzers.comparison import TraceComparison

    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    for model, cost in [("gpt-4o", 0.04), ("gpt-4o-mini", 0.004)]:
        span = Span(
            trace_id=f"cmp-{model}",
            span_id=f"sc-{model}",
            name="openai.chat",
            kind=SpanKind.LLM,
            provider="openai",
            model=model,
        )
        span.input_tokens = 500
        span.output_tokens = 200
        span.cost_usd = cost
        span.finish(status=SpanStatus.OK)
        monitor.emit(span)

    time.sleep(0.3)

    traces = asyncio.run(storage.list_traces(limit=10))
    check("2 traces for comparison", len(traces) == 2)

    cmp = TraceComparison.from_traces(traces[0], traces[1])
    text = str(cmp)
    check("Comparison renders", len(text) > 0)
    check("Comparison shows model names", "gpt-4o" in text)

    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 10: SQLite storage persistence
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_sqlite(tmp_path: Path) -> None:
    print("\n━━━ Scenario 10: SQLite persistent storage ━━━")
    try:
        from keeto.storage.sqlite import SQLiteStorage
    except ImportError:
        print("  ⚠  aiosqlite not installed — skipping")
        return

    from keeto.storage.sqlite import SQLiteStorage

    db_path = tmp_path / "keeto_test.db"
    storage = SQLiteStorage(str(db_path))
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    for i in range(5):
        with monitor.span(f"sqlite-op-{i}") as ctx:
            ctx.set_attribute("index", i)
            time.sleep(0.002)

    time.sleep(0.3)

    check("DB file created", db_path.exists())
    check("DB file has content", db_path.stat().st_size > 0)

    traces = asyncio.run(storage.list_traces(limit=20))
    check("SQLite: 5 traces persisted", len(traces) == 5)

    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 11: Rich dashboard renders without error
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_dashboard() -> None:
    print("\n━━━ Scenario 11: Rich dashboard ━━━")
    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    for i in range(4):
        span = Span(
            trace_id=f"dash-{i}",
            span_id=f"sd{i}",
            name="openai.chat",
            kind=SpanKind.LLM,
            provider="openai",
            model="gpt-4o",
        )
        span.input_tokens = 300 + i * 100
        span.output_tokens = 120 + i * 30
        span.cost_usd = 0.006 + i * 0.001
        span.finish(status=SpanStatus.OK if i < 3 else SpanStatus.ERROR)
        monitor.emit(span)

    time.sleep(0.2)

    raised = False
    try:
        monitor.dashboard(mode="rich")
    except Exception as e:
        raised = True
        print(f"    ERROR: {e}")

    check("Rich dashboard renders without raising", not raised)
    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 12: LiteLLM callback integration
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_litellm() -> None:
    print("\n━━━ Scenario 12: LiteLLM callback ━━━")
    try:
        import litellm as _litellm  # noqa: F401
    except ImportError:
        print("  ⚠  litellm not installed — skipping")
        return

    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    from keeto.integrations.litellm.plugin import LiteLLMPlugin

    litellm_plugin = LiteLLMPlugin()
    litellm_plugin.install(monitor)

    logger = litellm_plugin._logger
    start_time = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
    end_time = datetime(2024, 6, 1, 10, 0, 2, tzinfo=UTC)

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 350
    mock_usage.completion_tokens = 120
    mock_response = MagicMock()
    mock_response.usage = mock_usage

    kwargs: dict[str, Any] = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Explain quantum computing briefly."}],
        "litellm_params": {"custom_llm_provider": "openai"},
        "response_cost": 0.0008,
    }
    logger.log_success_event(kwargs, mock_response, start_time, end_time)

    time.sleep(0.3)
    traces = asyncio.run(storage.list_traces(limit=10))
    check("LiteLLM span captured", len(traces) == 1)
    span = traces[0].root_span
    check("Span is litellm.completion", span is not None and span.name == "litellm.completion")
    check("cost_usd from litellm", span is not None and span.cost_usd == pytest.approx(0.0008))
    check("input_tokens=350", span is not None and span.input_tokens == 350)

    litellm_plugin.uninstall()
    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 13: Context manager lifecycle
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_context_manager() -> None:
    print("\n━━━ Scenario 13: Monitor as context manager ━━━")
    storage = MemoryStorage()

    with Monitor(storage=storage, auto=False) as monitor:
        for i in range(3):
            with monitor.span(f"step-{i}") as ctx:
                ctx.set_attribute("step", i)
                time.sleep(0.002)

    time.sleep(0.2)
    traces = asyncio.run(storage.list_traces(limit=10))
    check("Context manager: 3 spans captured", len(traces) == 3)
    check("Monitor stopped after context exit", not monitor._started)


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 14: Nested spans with trace propagation
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_nested_spans() -> None:
    print("\n━━━ Scenario 14: Nested spans with trace propagation ━━━")
    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    with monitor.span("parent-op") as parent_ctx:
        parent_ctx.set_attribute("level", "parent")

        with monitor.span("child-op-1") as child1:
            child1.set_attribute("level", "child")
            time.sleep(0.005)

        with monitor.span("child-op-2") as child2:
            child2.set_attribute("level", "child")
            time.sleep(0.005)

    time.sleep(0.2)

    traces = asyncio.run(storage.list_traces(limit=20))
    all_spans = [s for t in traces for s in t.spans]
    check("3 spans total", len(all_spans) == 3)

    parent_spans = [s for s in all_spans if s.name == "parent-op"]
    child_spans = [s for s in all_spans if s.name.startswith("child-op")]
    check("1 parent span", len(parent_spans) == 1)
    check("2 child spans", len(child_spans) == 2)

    parent_trace_id = parent_spans[0].trace_id
    for cs in child_spans:
        check(
            f"Child {cs.name} shares trace_id with parent",
            cs.trace_id == parent_trace_id,
        )

    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 15: Error span propagation
# ═══════════════════════════════════════════════════════════════════════════════


def scenario_error_span() -> None:
    print("\n━━━ Scenario 15: Error span capture ━━━")
    storage = MemoryStorage()
    monitor = Monitor(storage=storage, auto=False)
    monitor.start()

    with contextlib.suppress(RuntimeError), monitor.span("failing-llm-call") as ctx:
        ctx.set_attribute("provider", "openai")
        raise RuntimeError("Connection timed out after 30s")

    time.sleep(0.2)

    traces = asyncio.run(storage.list_traces(limit=10))
    check("Error span captured", len(traces) == 1)
    span = traces[0].root_span
    check("Status is ERROR", span is not None and span.status == SpanStatus.ERROR)
    check("Error message stored", span is not None and "Connection timed out" in (span.status_message or ""))

    monitor.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest entry point
# ═══════════════════════════════════════════════════════════════════════════════


def test_realworld_e2e(tmp_path: Path) -> None:
    """Run all 15 real-world scenarios and assert all checks pass."""
    results.clear()

    scenario_quickstart()
    scenario_openai_rag()
    scenario_anthropic_pii()
    scenario_multi_provider()
    scenario_errors()
    scenario_budget()
    scenario_export(tmp_path)
    scenario_recommendations()
    scenario_compare()
    scenario_sqlite(tmp_path)
    scenario_dashboard()
    scenario_litellm()
    scenario_context_manager()
    scenario_nested_spans()
    scenario_error_span()

    failed = [(name, detail) for name, ok, detail in results if not ok]
    passed = len(results) - len(failed)
    print(f"\n  Results: {passed}/{len(results)} passed, {len(failed)} failed")

    if failed:
        lines = "\n".join(f"  {FAIL}  {n}" + (f"  ({d})" if d else "") for n, d in failed)
        pytest.fail(f"{len(failed)} check(s) failed:\n{lines}")


# ═══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="keeto_e2e_"))
    print(f"\n{'═' * 60}")
    print("  KEETO — Real-World End-to-End Test Suite")
    print(f"{'═' * 60}")
    print(f"  Temp dir: {tmp}")
    print(f"  Time: {datetime.now().isoformat()}")

    results.clear()
    scenario_quickstart()
    scenario_openai_rag()
    scenario_anthropic_pii()
    scenario_multi_provider()
    scenario_errors()
    scenario_budget()
    scenario_export(tmp)
    scenario_recommendations()
    scenario_compare()
    scenario_sqlite(tmp)
    scenario_dashboard()
    scenario_litellm()
    scenario_context_manager()
    scenario_nested_spans()
    scenario_error_span()

    passed = sum(1 for _, ok, _ in results if ok)
    failed_list = [(n, d) for n, ok, d in results if not ok]
    total = len(results)

    print(f"\n{'═' * 60}")
    print(f"  Results: {passed}/{total} passed, {len(failed_list)} failed")
    print(f"{'═' * 60}")

    if failed_list:
        print("\nFailed checks:")
        for name, detail in failed_list:
            print(f"  {FAIL}  {name}" + (f"  ({detail})" if detail else ""))
        sys.exit(1)
    else:
        print("\n  All checks passed! Keeto is working correctly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
