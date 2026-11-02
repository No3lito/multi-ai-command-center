"""Model price table and cost arithmetic (Decimal, never float)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import ROUND_UP, Decimal
from functools import lru_cache
from pathlib import Path

PRICES_FILE = Path(__file__).with_name("prices.json")
MTOK = Decimal(1_000_000)
MICRO = Decimal("0.000001")

# Conservative token estimate for budgeting before a call: ~2.5 characters per token
# overestimates typical English (about 4), so reservations err high.
CHARS_PER_TOKEN_ESTIMATE = 2.5
PROMPT_OVERHEAD_TOKENS = 64


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    long_context_threshold: int | None = None
    long_input: Decimal | None = None
    long_output: Decimal | None = None

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        rate_in, rate_out = self.input, self.output
        if self.long_context_threshold is not None and input_tokens > self.long_context_threshold:
            rate_in = self.long_input or rate_in
            rate_out = self.long_output or rate_out
        raw = (Decimal(input_tokens) * rate_in + Decimal(output_tokens) * rate_out) / MTOK
        return raw.quantize(MICRO, rounding=ROUND_UP)


@lru_cache
def price_table() -> dict[str, Price]:
    data = json.loads(PRICES_FILE.read_text())
    table: dict[str, Price] = {}
    for key, p in data["models"].items():
        table[key] = Price(
            input=Decimal(str(p["input"])),
            output=Decimal(str(p["output"])),
            long_context_threshold=p.get("long_context_threshold"),
            long_input=Decimal(str(p["long_input"])) if "long_input" in p else None,
            long_output=Decimal(str(p["long_output"])) if "long_output" in p else None,
        )
    return table


def price_for(provider: str, model: str) -> Price | None:
    return price_table().get(f"{provider}:{model}")


def estimate_input_tokens(prompt_chars: int) -> int:
    return math.ceil(prompt_chars / CHARS_PER_TOKEN_ESTIMATE) + PROMPT_OVERHEAD_TOKENS
