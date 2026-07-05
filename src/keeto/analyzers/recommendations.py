"""
Recommendations engine -- rule registry + report formatter.

Issues #63-#64 (carried from M3) and #66-#75 (M4).
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from keeto.core.span import Trace

# Suggested cheaper alternatives for expensive models (#69)
_CHEAPER_ALTERNATIVES: dict[str, str] = {
    "gpt-4o": "gpt-4o-mini",
    "gpt-4.1": "gpt-4.1-mini",
    "gpt-4.1-mini": "gpt-4.1-nano",
    "o1": "o4-mini",
    "o3": "o4-mini",
    "claude-opus-4-5": "claude-sonnet-4-5",
    "claude-opus-4-8": "claude-sonnet-4-6",
    "claude-3-opus-20240229": "claude-3-5-sonnet-20241022",
    "gemini-2.5-pro": "gemini-2.5-flash",
    "gemini-1.5-pro": "gemini-1.5-flash",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Recommendation:
    severity: str  # "info" | "warning" | "error"
    rule: str
    message: str
    trace_ids: list[str] = field(default_factory=list)


@dataclass
class RecommendationsReport:
    recommendations: list[Recommendation] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.recommendations:
            return "keeto: no recommendations -- everything looks good."
        lines = ["keeto recommendations:"]
        _sev = {"error": 0, "warning": 1, "info": 2}
        for r in sorted(self.recommendations, key=lambda x: _sev.get(x.severity, 3)):
            icon = {"info": "[i]", "warning": "[!]", "error": "[x]"}.get(r.severity, "[-]")
            lines.append(f"  {icon} [{r.rule}] {r.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rule ABC
# ---------------------------------------------------------------------------


class Rule(ABC):
    name: ClassVar[str]
    severity: ClassVar[str]

    @abstractmethod
    def check(self, traces: list[Trace]) -> list[Recommendation]: ...


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: list[Rule] = []

    def register(self, rule: Rule) -> None:
        self._rules.append(rule)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)


# ---------------------------------------------------------------------------
# Rule #67: prompt size optimization
# ---------------------------------------------------------------------------


class PromptSizeRule(Rule):
    name = "prompt_size"
    severity = "warning"

    THRESHOLD = 0.75  # flag when input_tokens > 75% of context window

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        from keeto._pricing import context_window

        results: list[Recommendation] = []
        for trace in traces:
            for span in trace.spans:
                if span.input_tokens is None or span.model is None:
                    continue
                window = context_window(span.model)
                if window is None:
                    continue
                ratio = span.input_tokens / window
                if ratio > self.THRESHOLD:
                    results.append(
                        Recommendation(
                            severity=self.severity,
                            rule=self.name,
                            message=(
                                f"Span '{span.name}' used {span.input_tokens:,} input tokens "
                                f"({ratio:.0%} of {span.model}'s {window:,}-token context window). "
                                f"Consider chunking or summarizing the prompt."
                            ),
                            trace_ids=[trace.trace_id],
                        )
                    )
        return results


# ---------------------------------------------------------------------------
# Rule #68: cache candidates
# ---------------------------------------------------------------------------


class CacheCandidatesRule(Rule):
    name = "cache_candidate"
    severity = "info"

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        # Fingerprint: model + message_count (a cheap proxy for identical prompts)
        fingerprint_counts: Counter[str] = Counter()
        fingerprint_trace_ids: dict[str, list[str]] = defaultdict(list)
        fingerprint_cached: dict[str, bool] = {}

        for trace in traces:
            for span in trace.spans:
                if span.model is None:
                    continue
                msg_count = span.attributes.get("llm.message_count")
                if msg_count is None:
                    continue
                fp = f"{span.model}:{msg_count}"
                # Use stored messages fingerprint if available for higher accuracy
                msgs = span.attributes.get("llm.messages")
                if msgs:
                    h = hashlib.md5(str(msgs).encode(), usedforsecurity=False).hexdigest()[:8]
                    fp = f"{span.model}:{h}"
                fingerprint_counts[fp] += 1
                fingerprint_trace_ids[fp].append(trace.trace_id)
                # Track whether any call in this fingerprint used cache
                already_cached = fingerprint_cached.get(fp, False)
                fingerprint_cached[fp] = already_cached or bool(span.cached_tokens)

        results: list[Recommendation] = []
        for fp, count in fingerprint_counts.items():
            if count >= 2 and not fingerprint_cached.get(fp, False):
                model = fp.split(":")[0]
                tids = list(dict.fromkeys(fingerprint_trace_ids[fp]))[:5]
                results.append(
                    Recommendation(
                        severity=self.severity,
                        rule=self.name,
                        message=(
                            f"Same prompt sent {count}x to '{model}' without prompt caching. "
                            f"Enable prompt caching to reduce costs on repeated context."
                        ),
                        trace_ids=tids,
                    )
                )
        return results


# ---------------------------------------------------------------------------
# Rule #69: model switch suggestions
# ---------------------------------------------------------------------------


class ModelSwitchRule(Rule):
    name = "model_switch"
    severity = "info"

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        from keeto._pricing import PRICES

        results: list[Recommendation] = []
        seen_models: set[str] = set()

        for trace in traces:
            for span in trace.spans:
                model = span.model
                if model is None or model in seen_models:
                    continue
                cheaper = _CHEAPER_ALTERNATIVES.get(model)
                if cheaper is None:
                    continue
                seen_models.add(model)
                # Calculate cost ratio
                provider = span.provider or "openai"
                p = PRICES.get(provider, {})
                orig_entry = p.get(model)
                cheaper_entry = p.get(cheaper)
                if orig_entry and cheaper_entry:
                    ratio = orig_entry.get("input", 1) / max(cheaper_entry.get("input", 1), 1e-9)
                    if ratio >= 3:
                        results.append(
                            Recommendation(
                                severity=self.severity,
                                rule=self.name,
                                message=(
                                    f"'{model}' is ~{ratio:.0f}x more expensive than '{cheaper}' "
                                    f"per input token. For non-complex tasks, consider '{cheaper}'."
                                ),
                                trace_ids=[trace.trace_id],
                            )
                        )
        return results


# ---------------------------------------------------------------------------
# Rule #70: context waste (large repeated system prompt)
# ---------------------------------------------------------------------------


class ContextWasteRule(Rule):
    name = "context_waste"
    severity = "warning"

    MIN_CALLS = 3  # need at least this many calls with the same system prompt
    MIN_FRACTION = 0.30  # system prompt must be >30% of input tokens to flag

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        system_prompt_calls: Counter[str] = Counter()
        system_prompt_trace: dict[str, list[str]] = defaultdict(list)

        for trace in traces:
            for span in trace.spans:
                sys_prompt = span.attributes.get("llm.system_prompt")
                if not sys_prompt or span.input_tokens is None:
                    continue
                # Use a hash of the system prompt to fingerprint
                h = hashlib.md5(str(sys_prompt).encode(), usedforsecurity=False).hexdigest()[:12]
                key = f"{span.model or 'unknown'}:{h}"
                # Only flag if system prompt is large relative to total input
                sys_tokens = len(str(sys_prompt).split())  # rough estimate
                if sys_tokens / max(span.input_tokens, 1) >= self.MIN_FRACTION:
                    system_prompt_calls[key] += 1
                    system_prompt_trace[key].append(trace.trace_id)

        results: list[Recommendation] = []
        for key, count in system_prompt_calls.items():
            if count >= self.MIN_CALLS:
                model = key.split(":")[0]
                tids = system_prompt_trace[key][:5]
                results.append(
                    Recommendation(
                        severity=self.severity,
                        rule=self.name,
                        message=(
                            f"Large system prompt repeated {count}x in calls to '{model}'. "
                            f"Consider prompt caching (Anthropic) or a cached prefix (OpenAI) "
                            f"to avoid re-processing the system prompt each call."
                        ),
                        trace_ids=tids,
                    )
                )
        return results


# ---------------------------------------------------------------------------
# Rule #71: retry loop detection
# ---------------------------------------------------------------------------


class RetryLoopRule(Rule):
    name = "retry_loop"
    severity = "warning"

    MAX_RETRIES = 3

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        results: list[Recommendation] = []
        for trace in traces:
            total_retries = sum(
                span.attributes.get("llm.retry_count", 0)
                for span in trace.spans
                if span.attributes.get("llm.retry_count")
            )
            if total_retries > self.MAX_RETRIES:
                results.append(
                    Recommendation(
                        severity=self.severity,
                        rule=self.name,
                        message=(
                            f"Trace {trace.trace_id[:8]} had {total_retries} retries. "
                            f"Excessive retries may indicate rate limiting or flaky prompts. "
                            f"Consider exponential back-off or prompt simplification."
                        ),
                        trace_ids=[trace.trace_id],
                    )
                )
        return results


# ---------------------------------------------------------------------------
# Rule #72: hallucination heuristics
# ---------------------------------------------------------------------------


class HallucinationHeuristicRule(Rule):
    name = "hallucination_heuristic"
    severity = "warning"

    OUTPUT_RATIO_THRESHOLD = 5.0  # output > 5x input tokens is suspicious
    NON_STOP_REASONS = frozenset({"length", "max_tokens", "content_filter"})

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        results: list[Recommendation] = []
        for trace in traces:
            for span in trace.spans:
                finish = span.attributes.get("llm.finish_reason") or span.attributes.get("llm.stop_reason")
                if finish in self.NON_STOP_REASONS:
                    results.append(
                        Recommendation(
                            severity=self.severity,
                            rule=self.name,
                            message=(
                                f"Span '{span.name}' stopped due to '{finish}' "
                                f"(not natural completion). "
                                f"Response may be truncated -- consider increasing max_tokens."
                            ),
                            trace_ids=[trace.trace_id],
                        )
                    )
                elif (
                    span.input_tokens
                    and span.output_tokens
                    and span.output_tokens > span.input_tokens * self.OUTPUT_RATIO_THRESHOLD
                ):
                    ratio = span.output_tokens / span.input_tokens
                    results.append(
                        Recommendation(
                            severity="info",
                            rule=self.name,
                            message=(
                                f"Span '{span.name}' produced {span.output_tokens:,} output tokens "
                                f"from {span.input_tokens:,} input ({ratio:.1f}x ratio). "
                                f"High output/input ratio -- review for verbosity."
                            ),
                            trace_ids=[trace.trace_id],
                        )
                    )
        return results


# ---------------------------------------------------------------------------
# Rule #73: cost anomaly detection
# ---------------------------------------------------------------------------


class CostAnomalyRule(Rule):
    name = "cost_anomaly"
    severity = "warning"

    Z_THRESHOLD = 2.0

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        from keeto.analyzers.cost import detect_cost_anomalies

        anomalies = detect_cost_anomalies(traces, self.Z_THRESHOLD)
        return [
            Recommendation(
                severity=self.severity,
                rule=self.name,
                message=(
                    f"Span '{a.span.name}' cost ${a.cost_usd:.4f} -- "
                    f"{a.z_score:.1f} std-devs above session mean ${a.session_mean_usd:.4f}. "
                    f"Check for unexpectedly large prompts or high-cost models."
                ),
                trace_ids=[a.trace_id],
            )
            for a in anomalies
        ]


# ---------------------------------------------------------------------------
# Rule #74: latency anomaly detection
# ---------------------------------------------------------------------------


class LatencyAnomalyRule(Rule):
    name = "latency_anomaly"
    severity = "info"

    Z_THRESHOLD = 2.0

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        from keeto.analyzers.performance import detect_latency_anomalies

        anomalies = detect_latency_anomalies(traces, self.Z_THRESHOLD)
        return [
            Recommendation(
                severity=self.severity,
                rule=self.name,
                message=(
                    f"Span '{a.span.name}' took {a.latency_ms:.0f}ms -- "
                    f"{a.z_score:.1f} std-devs above session mean {a.session_mean_ms:.0f}ms. "
                    f"Consider streaming for long-running requests."
                ),
                trace_ids=[a.trace_id],
            )
            for a in anomalies
        ]


# ---------------------------------------------------------------------------
# Rule #75: error pattern clustering
# ---------------------------------------------------------------------------


class ErrorPatternRule(Rule):
    name = "error_pattern"
    severity = "error"

    MIN_COUNT = 2  # only report clusters seen more than once

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        from keeto.analyzers.errors import cluster_errors

        clusters = cluster_errors(traces)
        return [
            Recommendation(
                severity=self.severity,
                rule=self.name,
                message=(f"Error '{c.pattern}' occurred {c.count}x. Example: {c.example_message[:100]}"),
                trace_ids=c.trace_ids[:5],
            )
            for c in clusters
            if c.count >= self.MIN_COUNT
        ]


# ---------------------------------------------------------------------------
# Rule #64 (carried from M3): agent loop detection
# ---------------------------------------------------------------------------


class AgentLoopRule(Rule):
    name = "agent_loop"
    severity = "warning"

    MAX_SAME_PROMPT_CALLS = 3

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        prompt_counts: Counter[str] = Counter()
        prompt_trace_ids: dict[str, list[str]] = defaultdict(list)

        for trace in traces:
            for span in trace.spans:
                messages = span.attributes.get("llm.message_count")
                if messages is not None and span.model:
                    key = f"{span.model}:{messages}"
                    prompt_counts[key] += 1
                    prompt_trace_ids[key].append(trace.trace_id)

        results: list[Recommendation] = []
        for key, count in prompt_counts.items():
            if count > self.MAX_SAME_PROMPT_CALLS:
                model, msg_count = key.split(":", 1)
                tids = list(dict.fromkeys(prompt_trace_ids[key]))[:5]
                results.append(
                    Recommendation(
                        severity=self.severity,
                        rule=self.name,
                        message=(
                            f"Model '{model}' called {count}x with {msg_count} messages — "
                            f"possible agent loop. Consider adding a max-iterations guard."
                        ),
                        trace_ids=tids,
                    )
                )
        return results


# ---------------------------------------------------------------------------
# Rule #63 (carried from M3): provider cost comparison
# ---------------------------------------------------------------------------


class CostComparisonRule(Rule):
    name = "cost_comparison"
    severity = "info"

    def check(self, traces: list[Trace]) -> list[Recommendation]:
        from keeto.analyzers.cost import aggregate_cost_by_provider

        totals = aggregate_cost_by_provider(traces)
        if len(totals) < 2:
            return []

        providers = list(totals.keys())
        most_expensive = providers[0]
        cheapest = providers[-1]

        if totals[most_expensive] > totals[cheapest] * 3:
            return [
                Recommendation(
                    severity=self.severity,
                    rule=self.name,
                    message=(
                        f"'{most_expensive}' costs ${totals[most_expensive]:.4f} "
                        f"vs '{cheapest}' at ${totals[cheapest]:.4f} — "
                        f"consider shifting equivalent workloads to the cheaper provider."
                    ),
                )
            ]
        return []


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _default_registry() -> RuleRegistry:
    registry = RuleRegistry()
    for rule_cls in [
        PromptSizeRule,
        CacheCandidatesRule,
        ModelSwitchRule,
        ContextWasteRule,
        RetryLoopRule,
        HallucinationHeuristicRule,
        CostAnomalyRule,
        LatencyAnomalyRule,
        ErrorPatternRule,
        AgentLoopRule,
        CostComparisonRule,
    ]:
        registry.register(rule_cls())
    return registry


class RecommendationsEngine:
    def __init__(self, registry: RuleRegistry | None = None) -> None:
        self._registry = registry or _default_registry()

    def analyze(self, traces: list[Trace]) -> RecommendationsReport:
        report = RecommendationsReport()
        for rule in self._registry.rules:
            try:
                recs = rule.check(traces)
                report.recommendations.extend(recs)
            except Exception:
                pass  # never crash the caller due to a rule failure
        return report
