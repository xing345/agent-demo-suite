"""Usage accounting and cost: never invent numbers."""

from packages.model_gateway.usage import PriceTable, usage_from_response

PRICES = PriceTable({"demo": (1.0, 2.0)})


def test_missing_usage_block_is_reported_as_unavailable() -> None:
    usage = usage_from_response(None, model="demo", prices=PRICES)

    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.total_tokens is None
    assert usage.cost_usd is None
    assert usage.source == "unavailable"


def test_provider_usage_is_used_verbatim() -> None:
    usage = usage_from_response(
        {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        model="demo",
        prices=PRICES,
    )

    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.total_tokens == 1500
    assert usage.source == "provider"
    assert usage.cost_usd == 0.002


def test_total_is_derived_only_when_both_counts_exist() -> None:
    derived = usage_from_response(
        {"prompt_tokens": 10, "completion_tokens": 5}, model="demo", prices=PRICES
    )
    partial = usage_from_response({"prompt_tokens": 10}, model="demo", prices=PRICES)

    assert derived.total_tokens == 15
    assert partial.total_tokens is None
    assert partial.cost_usd is None


def test_unknown_model_yields_no_cost_estimate() -> None:
    usage = usage_from_response(
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        model="unpriced-model",
        prices=PRICES,
    )

    assert usage.cost_usd is None
    assert usage.source == "provider"


def test_price_table_is_configurable_and_optional() -> None:
    assert PriceTable().cost("demo", 1000, 1000) is None
    assert PriceTable({"demo": (3.0, 0.0)}).cost("demo", 1_000_000, 0) == 3.0


def test_negative_or_non_integer_tokens_are_ignored() -> None:
    usage = usage_from_response(
        {"prompt_tokens": -1, "completion_tokens": "many", "total_tokens": 5},
        model="demo",
        prices=PRICES,
    )

    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.cost_usd is None