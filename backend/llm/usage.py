"""Usage ledger: prices every LLM call and returns its cost to the caller (#18).

The cost is never read back from shared state: concurrent calls (another game,
a background extraction) cannot overwrite each other's cost.
"""

import logging

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


def is_unpriced(provider_name: str, model: str) -> bool:
    """True when the model has no known price: its calls are logged at $0, flagged unknown."""
    p = lookup_pricing(model, provider_name)
    return p.input == p.output == p.cache_write == p.cache_read == 0


class UsageLedger:
    """Prices each LLM call and returns its cost to the caller; keeps no totals.

    The account totals are read from llm_calls (repos/llm_calls.py, #106).
    """

    def record(self, purpose: str, provider_name: str, model: str, usage: LLMUsage) -> dict:
        cost = call_cost(usage, provider_name, model)
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


_ledger = UsageLedger()


def get_usage_ledger() -> UsageLedger:
    return _ledger
