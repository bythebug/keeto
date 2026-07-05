"""
Rule-based recommendations engine.

Full implementation in Milestone 4 (issues #66–#80). This stub returns
an empty report so the Monitor.recommendations() call works today.
"""

from __future__ import annotations

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
        # Rules will be registered here in Milestone 4
        return report
