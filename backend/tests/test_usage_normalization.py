"""Usage-normalization unit tests across mocked provider payloads + cost estimation."""

from __future__ import annotations

from decimal import Decimal

from app.providers.pricing import estimate_cost, load_rate_card
from app.providers.usage import NormalizedUsage, normalize_usage


def test_openai_style_usage():
    raw = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}
    u = normalize_usage(raw)
    assert u.input_tokens == 1000
    assert u.output_tokens == 200
    assert u.total_tokens == 1200
    assert u.thinking_tokens == 0


def test_gemini_style_usage_with_cache_and_thinking():
    raw = {
        "prompt_token_count": 5000,
        "candidates_token_count": 800,
        "total_token_count": 6300,
        "cached_content_token_count": 1500,
        "thoughts_token_count": 500,
    }
    u = normalize_usage(raw)
    assert u.input_tokens == 5000
    assert u.cached_tokens == 1500
    assert u.thinking_tokens == 500
    # output is net of thinking (800 includes the 500 thinking tokens)
    assert u.output_tokens == 300


def test_nested_details_usage():
    raw = {
        "prompt_tokens": 2000,
        "completion_tokens": 1000,
        "prompt_tokens_details": {"cached_tokens": 400},
        "completion_tokens_details": {"reasoning_tokens": 600},
    }
    u = normalize_usage(raw)
    assert u.cached_tokens == 400
    assert u.thinking_tokens == 600
    assert u.output_tokens == 400  # 1000 - 600 reasoning
    assert u.total_tokens == 2000 + 400 + 600


def test_litellm_usage_object_like():
    class _Usage:
        def model_dump(self):
            return {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    u = normalize_usage(_Usage())
    assert u.input_tokens == 10
    assert u.output_tokens == 5


def test_cost_estimation_gemini_flash():
    # gemini-2.5-flash: $0.3/M input, $2.5/M output, $0.03/M cache
    usage = NormalizedUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        thinking_tokens=0,
        cached_tokens=0,
        total_tokens=2_000_000,
    )
    cost = estimate_cost(pricing_ref="gemini-2.5-flash", usage=usage)
    assert cost.input_usd == Decimal("0.3")
    assert cost.output_usd == Decimal("2.5")
    assert cost.total_usd == Decimal("2.8")
    assert cost.pricing_ref == "gemini-2.5-flash"


def test_cost_estimation_discounts_cached_input_and_prices_thinking():
    usage = NormalizedUsage(
        input_tokens=1_000_000,
        output_tokens=0,
        thinking_tokens=1_000_000,
        cached_tokens=500_000,  # half the input is cached
        total_tokens=2_000_000,
    )
    cost = estimate_cost(pricing_ref="gemini-2.5-flash", usage=usage)
    # uncached input: 500k @ 0.3/M = 0.15 ; cache: 500k @ 0.03/M = 0.015 ; thinking: 1M @ 2.5/M = 2.5
    assert cost.input_usd == Decimal("0.15")
    assert cost.cache_usd == Decimal("0.015")
    assert cost.thinking_usd == Decimal("2.5")
    assert cost.total_usd == Decimal("2.665")


def test_regional_multiplier_applies_premium():
    usage = NormalizedUsage(input_tokens=1_000_000, total_tokens=1_000_000)
    base = estimate_cost(pricing_ref="claude-sonnet-4-6", usage=usage, region="default")
    regional = estimate_cost(pricing_ref="claude-sonnet-4-6", usage=usage, region="regional")
    assert regional.input_usd == base.input_usd * Decimal("1.1")


def test_unknown_pricing_ref_is_zero_not_error():
    cost = estimate_cost(pricing_ref="does-not-exist", usage=NormalizedUsage(input_tokens=10))
    assert cost.total_usd == Decimal("0")
    assert cost.pricing_ref is None


def test_rate_card_loads():
    card = load_rate_card()
    assert "gemini-2.5-flash" in card["models"]
    assert card["models"]["gemini-2.5-flash"]["input_usd_per_million"] == 0.3
