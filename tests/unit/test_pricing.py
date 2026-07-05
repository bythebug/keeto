"""Tests for the pricing / cost calculation module."""

import pytest

from keeto._pricing import PRICES, cost_usd


class TestCostUsd:
    def test_openai_gpt4o(self) -> None:
        c = cost_usd("openai", "gpt-4o", input_tokens=1000, output_tokens=500)
        assert c is not None
        # 1000 * 2.50/1M + 500 * 10.00/1M = 0.0025 + 0.005 = 0.0075
        assert c == pytest.approx(0.0075, rel=1e-4)

    def test_openai_with_cached_tokens(self) -> None:
        # 800 normal + 200 cached input, 500 output
        c = cost_usd("openai", "gpt-4o", input_tokens=1000, output_tokens=500, cached_tokens=200)
        assert c is not None
        # 800 * 2.50/1M + 200 * 1.25/1M + 500 * 10.00/1M
        expected = (800 * 2.50 + 200 * 1.25 + 500 * 10.00) / 1_000_000
        assert c == pytest.approx(expected, rel=1e-4)

    def test_anthropic_claude(self) -> None:
        c = cost_usd(
            "anthropic",
            "claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
        )
        assert c is not None
        # 1000 * 3.00/1M + 500 * 15.00/1M
        assert c == pytest.approx(0.003 + 0.0075, rel=1e-4)

    def test_unknown_provider_returns_none(self) -> None:
        assert cost_usd("unknownprovider", "some-model", 100, 50) is None

    def test_unknown_model_returns_none(self) -> None:
        assert cost_usd("openai", "gpt-999-turbo-xtreme", 100, 50) is None

    def test_zero_tokens(self) -> None:
        c = cost_usd("openai", "gpt-4o", input_tokens=0, output_tokens=0)
        assert c == pytest.approx(0.0)

    def test_google_gemini(self) -> None:
        c = cost_usd("google", "gemini-2.5-flash", input_tokens=10_000, output_tokens=2_000)
        assert c is not None
        assert c > 0

    def test_all_providers_have_valid_prices(self) -> None:
        for provider, models in PRICES.items():
            for model, price in models.items():
                assert "input" in price, f"{provider}/{model} missing 'input' price"
                assert price["input"] >= 0
