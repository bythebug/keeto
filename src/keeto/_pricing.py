"""
Provider model pricing table.

Prices are in USD per 1M tokens. Source: official provider pricing pages.
Update by editing the PRICES dict — a future automated update mechanism
will keep this in sync with a remote prices.json.
"""

from __future__ import annotations

# Structure: provider → model → {"input": $/1M, "output": $/1M, "cached_input": $/1M}
PRICES: dict[str, dict[str, dict[str, float]]] = {
    "openai": {
        # GPT-4o family
        "gpt-4o": {"input": 2.50, "output": 10.00, "cached_input": 1.25},
        "gpt-4o-2024-11-20": {"input": 2.50, "output": 10.00, "cached_input": 1.25},
        "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00, "cached_input": 1.25},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached_input": 0.075},
        "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60, "cached_input": 0.075},
        # GPT-4.1 family
        "gpt-4.1": {"input": 2.00, "output": 8.00, "cached_input": 0.50},
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cached_input": 0.10},
        "gpt-4.1-nano": {"input": 0.10, "output": 0.40, "cached_input": 0.025},
        # o-series reasoning
        "o1": {"input": 15.00, "output": 60.00, "cached_input": 7.50},
        "o1-mini": {"input": 1.10, "output": 4.40, "cached_input": 0.55},
        "o3": {"input": 10.00, "output": 40.00, "cached_input": 2.50},
        "o3-mini": {"input": 1.10, "output": 4.40, "cached_input": 0.55},
        "o4-mini": {"input": 1.10, "output": 4.40, "cached_input": 0.275},
        # Embeddings
        "text-embedding-3-small": {"input": 0.02, "output": 0.0},
        "text-embedding-3-large": {"input": 0.13, "output": 0.0},
        "text-embedding-ada-002": {"input": 0.10, "output": 0.0},
    },
    "anthropic": {
        # Claude 4 family
        "claude-opus-4-5": {"input": 15.00, "output": 75.00, "cached_input": 1.50},
        "claude-opus-4-8": {"input": 15.00, "output": 75.00, "cached_input": 1.50},
        "claude-sonnet-4-5": {"input": 3.00, "output": 15.00, "cached_input": 0.30},
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cached_input": 0.30},
        "claude-haiku-4-5": {"input": 0.80, "output": 4.00, "cached_input": 0.08},
        # Claude 3.x family
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00, "cached_input": 0.30},
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00, "cached_input": 0.08},
        "claude-3-opus-20240229": {"input": 15.00, "output": 75.00, "cached_input": 1.50},
        "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00, "cached_input": 0.30},
        "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25, "cached_input": 0.03},
    },
    "google": {
        "gemini-2.5-pro": {"input": 1.25, "output": 10.00, "cached_input": 0.31},
        "gemini-2.5-flash": {"input": 0.15, "output": 0.60, "cached_input": 0.04},
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "cached_input": 0.025},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00, "cached_input": 0.31},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30, "cached_input": 0.01875},
    },
    "ollama": {},
}


def cost_usd(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float | None:
    """
    Calculate USD cost for a request. Returns None if pricing is unknown.
    Prices are stored per 1M tokens.
    """
    # Ollama runs locally — always free
    if provider == "ollama":
        return 0.0

    p = PRICES.get(provider, {})
    # Try exact match, then strip date suffix (e.g. -20241022)
    entry = p.get(model)
    if entry is None:
        base = model.rsplit("-", 1)[0] if model.count("-") > 1 else model
        entry = p.get(base)
    if entry is None:
        return None

    normal_input = max(0, input_tokens - cached_tokens)
    cost = (
        normal_input * entry.get("input", 0.0)
        + cached_tokens * entry.get("cached_input", entry.get("input", 0.0))
        + output_tokens * entry.get("output", 0.0)
    ) / 1_000_000

    return round(cost, 8)
