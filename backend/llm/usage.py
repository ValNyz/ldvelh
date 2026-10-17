"""Usage ledger: records every LLM call and returns its cost to the caller (#18).

The cost is never read back from shared state: concurrent calls (another game,
a background extraction) cannot overwrite each other's cost.
"""

import logging
from dataclasses import dataclass

from services.llm_providers import LLMUsage
from services.pricing import lookup_pricing

logger = logging.getLogger(__name__)


def call_cost(usage: LLMUsage, provider_name: str, model: str) -> float:
    """USD cost of one call from its token usage."""
    p = lookup_pricing(model, provider_name)
    return (
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_creation_input_tokens * p.cache_write
        + usage.cache_read_input_tokens * p.cache_read
    ) / 1_000_000


def cost_from_stored(usage_data: dict) -> float:
    """USD cost from a stored usage dict (read from DB).

    Expected keys: input_tokens, output_tokens, cache_creation_input_tokens,
    cache_read_input_tokens, model, provider.
    """
    usage = LLMUsage(
        input_tokens=usage_data.get("input_tokens", 0),
        output_tokens=usage_data.get("output_tokens", 0),
        cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
    )
    return round(
        call_cost(usage, usage_data.get("provider", "anthropic"), usage_data.get("model", "")), 6
    )


@dataclass
class _Totals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0


class UsageLedger:
    """Process-wide usage totals, keyed by (purpose, provider, model)."""

    def __init__(self):
        self._totals: dict[tuple[str, str, str], _Totals] = {}

    def record(self, purpose: str, provider_name: str, model: str, usage: LLMUsage) -> dict:
        cost = call_cost(usage, provider_name, model)
        t = self._totals.setdefault((purpose, provider_name, model), _Totals())
        t.input_tokens += usage.input_tokens
        t.output_tokens += usage.output_tokens
        t.cache_creation_input_tokens += usage.cache_creation_input_tokens
        t.cache_read_input_tokens += usage.cache_read_input_tokens
        t.calls += 1
        t.cost_usd += cost
        logger.debug(
            f"[COST] {purpose}/{provider_name}/{model}: +{usage.input_tokens}in "
            f"+{usage.output_tokens}out (cache_read={usage.cache_read_input_tokens}) = ${cost:.6f}"
        )
        return {
            "cost_usd": round(cost, 6),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "model": model,
            "provider": provider_name,
        }

    def get_summary(self) -> dict:
        purposes: dict[str, dict] = {}
        total = 0.0
        for (purpose, _provider, model), t in self._totals.items():
            total += t.cost_usd
            entry = purposes.setdefault(purpose, {"models": {}, "cost_usd": 0.0, "calls": 0})
            m = entry["models"].setdefault(model, {
                "input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0, "calls": 0, "cost_usd": 0.0,
            })
            for field in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                          "cache_read_input_tokens", "calls"):
                m[field] += getattr(t, field)
            m["cost_usd"] = round(m["cost_usd"] + t.cost_usd, 6)
            entry["cost_usd"] = round(entry["cost_usd"] + t.cost_usd, 6)
            entry["calls"] += t.calls
        return {"purposes": purposes, "total_cost_usd": round(total, 6)}


_ledger = UsageLedger()


def get_usage_ledger() -> UsageLedger:
    return _ledger
