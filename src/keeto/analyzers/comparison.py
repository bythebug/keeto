"""Trace comparison — monitor.compare(trace_a, trace_b)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keeto.core.span import Trace


@dataclass
class TraceComparison:
    trace_id_a: str
    trace_id_b: str
    model_a: str | None
    model_b: str | None
    latency_a_ms: float | None
    latency_b_ms: float | None
    cost_a_usd: float
    cost_b_usd: float
    input_tokens_a: int
    input_tokens_b: int
    output_tokens_a: int
    output_tokens_b: int

    @classmethod
    def from_traces(cls, a: Trace, b: Trace) -> TraceComparison:
        return cls(
            trace_id_a=a.trace_id,
            trace_id_b=b.trace_id,
            model_a=a.model,
            model_b=b.model,
            latency_a_ms=a.latency_ms,
            latency_b_ms=b.latency_ms,
            cost_a_usd=a.total_cost_usd,
            cost_b_usd=b.total_cost_usd,
            input_tokens_a=a.total_input_tokens,
            input_tokens_b=b.total_input_tokens,
            output_tokens_a=a.total_output_tokens,
            output_tokens_b=b.total_output_tokens,
        )

    @property
    def latency_delta_ms(self) -> float | None:
        if self.latency_a_ms is None or self.latency_b_ms is None:
            return None
        return self.latency_b_ms - self.latency_a_ms

    @property
    def cost_delta_usd(self) -> float:
        return self.cost_b_usd - self.cost_a_usd

    def __str__(self) -> str:
        lines = [
            "keeto: trace comparison",
            f"  {'Field':<20} {'A':>14} {'B':>14} {'Δ':>14}",
            f"  {'-' * 64}",
        ]

        def _row(label: str, a: object, b: object, delta: object = None) -> str:
            d = f"{delta!s}" if delta is not None else ""
            return f"  {label:<20} {a!s:>14} {b!s:>14} {d:>14}"

        lines.append(f"  {'Trace ID':<20} {self.trace_id_a[:12]:>14} {self.trace_id_b[:12]:>14}")
        ma = (self.model_a or "?")[:14]
        mb = (self.model_b or "?")[:14]
        lines.append(f"  {'Model':<20} {ma:>14} {mb:>14}")

        if self.latency_a_ms is not None or self.latency_b_ms is not None:
            a_lat = f"{self.latency_a_ms:.0f}ms" if self.latency_a_ms else "?"
            b_lat = f"{self.latency_b_ms:.0f}ms" if self.latency_b_ms else "?"
            delta = f"{self.latency_delta_ms:+.0f}ms" if self.latency_delta_ms is not None else ""
            lines.append(f"  {'Latency':<20} {a_lat:>14} {b_lat:>14} {delta:>14}")

        lines.append(
            _row(
                "Cost (USD)",
                f"${self.cost_a_usd:.6f}",
                f"${self.cost_b_usd:.6f}",
                f"{'+' if self.cost_delta_usd >= 0 else ''}${self.cost_delta_usd:.6f}",
            )
        )
        lines.append(
            _row(
                "Input tokens",
                self.input_tokens_a,
                self.input_tokens_b,
                f"{self.input_tokens_b - self.input_tokens_a:+d}",
            )
        )
        lines.append(
            _row(
                "Output tokens",
                self.output_tokens_a,
                self.output_tokens_b,
                f"{self.output_tokens_b - self.output_tokens_a:+d}",
            )
        )
        return "\n".join(lines)
