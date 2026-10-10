"""USD per million tokens, used to record the cost of every call and enforce the daily cap.

Update when Anthropic changes prices; OpenRouter passes them through unchanged. An unknown model is
billed at the most expensive known rate, so a missing entry can only make the cap stricter, never
looser.
"""

from __future__ import annotations

import re
from decimal import Decimal

# model id: (input, output) USD per 1M tokens
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-fable-5-1": (Decimal("10"), Decimal("50")),
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-haiku-4-5": (Decimal("1"), Decimal("5")),
    "claude-opus-4-8": (Decimal("5"), Decimal("25")),
}
_FALLBACK = max(PRICES.values(), key=lambda p: p[1])
_MILLION = Decimal(1_000_000)


def canonical(model: str) -> str:
    """Anthropic's id for a model, also from OpenRouter's (anthropic/claude-opus-5.5-20260921)."""
    name = re.sub(r"-\d{8}$", "", model.rsplit("/", 1)[-1])
    return name.replace(".", "-")


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    inp, out = PRICES.get(canonical(model), _FALLBACK)
    return (inp * input_tokens + out * output_tokens) / _MILLION
