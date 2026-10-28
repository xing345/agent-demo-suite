"""Token accounting and cost.

Costs are only produced from an explicitly configured price table; an unknown
model yields ``cost_usd=None`` rather than an invented number.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

PRICE_UNIT = 1_000_000


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    source: str = "unavailable"


class PriceTable:
    """USD per 1M tokens: ``{"model": (input_price, output_price)}``."""

    def __init__(self, prices: Mapping[str, tuple[float, float]] | None = None) -> None:
        self._prices = dict(prices or {})

    def cost(
        self,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> float | None:
        price = self._prices.get(model)
        if price is None or input_tokens is None or output_tokens is None:
            return None
        input_price, output_price = price
        total = input_tokens / PRICE_UNIT * input_price + output_tokens / PRICE_UNIT * output_price
        return round(total, 8)


def usage_from_response(
    payload: object,
    *,
    model: str,
    prices: PriceTable | None = None,
) -> Usage:
    if not isinstance(payload, dict):
        return Usage()

    input_tokens = _as_count(payload.get("prompt_tokens"))
    output_tokens = _as_count(payload.get("completion_tokens"))
    total_tokens = _as_count(payload.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    cost = (prices or PriceTable()).cost(model, input_tokens, output_tokens)
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost,
        source="provider",
    )


def _as_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None