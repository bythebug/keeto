# API Reference

## Module-level helpers

::: keeto.trace

## Monitor

::: keeto.core.monitor.Monitor
    options:
      members:
        - start
        - stop
        - span
        - trace
        - pipeline_breakdown
        - emit
        - dashboard
        - export
        - recommendations
        - compare
        - set_budget
        - set_token_budget
        - cost_summary
        - token_summary
        - import_langsmith
        - traces

## Span and Trace models

::: keeto.core.span.Span

::: keeto.core.span.Trace

::: keeto.core.span.SpanKind

::: keeto.core.span.SpanStatus

## Events

::: keeto.core.events.BaseEvent

::: keeto.core.events.LLMRequestStartEvent

::: keeto.core.events.LLMRequestEndEvent

::: keeto.core.events.LLMStreamChunkEvent

::: keeto.core.events.ToolCallStartEvent

::: keeto.core.events.ToolCallEndEvent

::: keeto.core.events.EmbeddingRequestEvent

::: keeto.core.events.ErrorEvent

## Storage

::: keeto.storage.memory.MemoryStorage

::: keeto.storage.sqlite.SQLiteStorage

## Exporters

::: keeto.exporters.json.export_json

::: keeto.exporters.csv.export_csv

## Analysis

::: keeto.analyzers.recommendations.RecommendationsReport

::: keeto.analyzers.recommendations.RecommendationsEngine

::: keeto.analyzers.comparison.TraceComparison

## Plugin system

::: keeto.plugins.base.Plugin

::: keeto.plugins.registry.PluginRegistry
