"""
Rule-based recommendations engine — Milestone 3 additions.

Issues #63 (provider cost comparison) and #64 (agent loop detection)
are implemented here. Full rule suite comes in Milestone 4 (#66–#80).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from keeto.core.span import Trace


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
            return "keeto: no recommendations — everything looks good."
        lines = ["keeto recommendations:"]
        for r in self.recommendations:
            icon = {"info": "ℹ", "warning": "⚠", "error": "✗"}.get(r.severity, "•")
            lines.append(f"  {icon} [{r.rule}] {r.message}")
        return "\n".join(lines)


class RecommendationsEngine:
    def analyze(self, traces: list[Trace]) -> RecommendationsReport:
        report = RecommendationsReport()
        self._check_agent_loops(traces, report)
        self._check_cost_by_provider(traces, report)
        return report

    # ------------------------------------------------------------------
    # Issue #64: agent loop detection
    # ------------------------------------------------------------------

    def _check_agent_loops(self, traces: list[Trace], report: RecommendationsReport) -> None:
        prompt_counts: Counter[str] = Counter()
        prompt_trace_ids: dict[str, list[str]] = defaultdict(list)

        for trace in traces:
            for span in trace.spans:
                messages = span.attributes.get("llm.message_count")
                # Use a fingerprint: model + message_count + first few chars of name
                if messages is not None and span.model:
                    key = f"{span.model}:{messages}"
                    prompt_counts[key] += 1
                    prompt_trace_ids[key].append(trace.trace_id)

        for key, count in prompt_counts.items():
            if count > 3:
                model, msg_count = key.split(":", 1)
                tids = prompt_trace_ids[key][:5]
                report.recommendations.append(
                    Recommendation(
                        severity="warning",
                        rule="agent_loop",
                        message=(
                            f"Model '{model}' called {count}x with {msg_count} messages — "
                            f"possible agent loop. Consider adding a max-iterations guard."
                        ),
                        trace_ids=tids,
                    )
                )

    # ------------------------------------------------------------------
    # Issue #63: provider cost comparison
    # ------------------------------------------------------------------

    def _check_cost_by_provider(self, traces: list[Trace], report: RecommendationsReport) -> None:
        cost_by_provider: dict[str, float] = defaultdict(float)
        call_count: dict[str, int] = defaultdict(int)

        for trace in traces:
            for span in trace.spans:
                if span.provider and span.cost_usd is not None:
                    cost_by_provider[span.provider] += span.cost_usd
                    call_count[span.provider] += 1

        if len(cost_by_provider) < 2:
            return

        providers = sorted(cost_by_provider, key=lambda p: cost_by_provider[p], reverse=True)
        most_expensive = providers[0]
        cheapest = providers[-1]

        if cost_by_provider[most_expensive] > cost_by_provider[cheapest] * 3:
            report.recommendations.append(
                Recommendation(
                    severity="info",
                    rule="cost_comparison",
                    message=(
                        f"'{most_expensive}' costs ${cost_by_provider[most_expensive]:.4f} "
                        f"vs '{cheapest}' at ${cost_by_provider[cheapest]:.4f} — "
                        f"consider shifting equivalent workloads to the cheaper provider."
                    ),
                )
            )
