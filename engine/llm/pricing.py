"""USD per million tokens, used to record the cost of every call and enforce the daily cap.

Update when Anthropic changes prices. An unknown model is billed at the most expensive known rate,
so a missing entry can only make the cap stricter, never looser.
"""

from __future__ import annotations

from decimal import Decimal

# model id: (input, output) USD per 1M tokens
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-haiku-4-5": (Decimal("1"), Decimal("5")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25")),
}
_FALLBACK = max(PRICES.values(), key=lambda p: p[1])
_MILLION = Decimal(1_000_000)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    inp, out = PRICES.get(model, _FALLBACK)
    return (inp * input_tokens + out * output_tokens) / _MILLION
