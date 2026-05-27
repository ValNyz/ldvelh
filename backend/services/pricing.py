"""Central LLM pricing lookup.

Source: litellm's `model_prices_and_context_window.json`, vendored as
`services/model_prices.json`. Refresh periodically:

    curl -fsSL https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json \
        -o backend/services/model_prices.json

The JSON file uses USD per token; we multiply by 1M to match the
ModelPricing schema (USD per million tokens).

IMPORTANT: `wandb/*` and several `mistral/*` entries have been
hand-curated to match the vendors' official pricing pages:
  - https://wandb.ai/site/inference (10x off in upstream litellm)
  - https://mistral.ai/pricing       (stale aliases for "latest" tags
    and missing new model dates like Medium 3.5, Small 4, Ministral 3,
    Voxtral text pricing).
After refreshing this file from litellm, diff the wandb and mistral
blocks and re-apply the manual corrections.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_PRICING_FILE = Path(__file__).parent / "model_prices.json"


@dataclass(frozen=True)
class ModelPricing:
    """Cost per million tokens (USD)."""

    input: float = 0.0
    output: float = 0.0
    cache_write: float = 0.0
    cache_read: float = 0.0


def _load() -> dict[str, ModelPricing]:
    """Load and normalize the litellm pricing file once."""
    if not _PRICING_FILE.exists():
        logger.warning(f"[pricing] {_PRICING_FILE} not found; cost tracking disabled")
        return {}
    try:
        raw = json.loads(_PRICING_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"[pricing] failed to load {_PRICING_FILE}: {e}")
        return {}

    result: dict[str, ModelPricing] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue  # skip "sample_spec" or other metadata
        input_cost = entry.get("input_cost_per_token")
        output_cost = entry.get("output_cost_per_token")
        if input_cost is None and output_cost is None:
            continue
        result[key] = ModelPricing(
            input=_normalize_rate(input_cost),
            output=_normalize_rate(output_cost),
            cache_write=_normalize_rate(entry.get("cache_creation_input_token_cost")),
            cache_read=_normalize_rate(entry.get("cache_read_input_token_cost")),
        )
    return result


# Real per-token prices are always tiny (frontier GPT-4 is ~$30/M = 3e-5/token).
# Anything >= this threshold is almost certainly already in "per million"
# units (litellm has data errors of this kind, e.g. all wandb entries store
# per-million values in the per-token field).
_PER_TOKEN_PRICE_CEILING = 0.001  # $1000 per million tokens — well above frontier


def _normalize_rate(value: float | None) -> float:
    """Convert a litellm "cost per token" field to USD per million tokens.

    If the value already looks like a per-million rate (> ceiling), trust it
    and don't multiply. This corrects litellm's mislabeled wandb entries.
    """
    if not value:
        return 0.0
    if value >= _PER_TOKEN_PRICE_CEILING:
        return value  # already per-million
    return value * 1_000_000


_PRICING: dict[str, ModelPricing] = _load()

# Pricing registered at runtime by providers that ship pricing inline in
# their /v1/models response (e.g. Nous Research). Keyed by "{provider}/{model}".
# Takes precedence over the vendored litellm table.
_DYNAMIC_PRICING: dict[str, ModelPricing] = {}


def register_pricing(model: str, provider: str, pricing: ModelPricing) -> None:
    """Register live per-million-token pricing for a model.

    Use when the provider's own API returns the authoritative pricing,
    so cost computation later doesn't need to depend on the vendored file.
    """
    if not model or not provider:
        return
    _DYNAMIC_PRICING[f"{provider}/{model}"] = pricing


def lookup_pricing(model: str, provider: str | None = None) -> ModelPricing:
    """Return USD-per-million-token rates for a model.

    Resolution order:
      1. Runtime-registered pricing (Nous and other vendors that expose
         pricing in their /v1/models response).
      2. Vendored litellm table by exact model id.
      3. Vendored litellm table by "{provider}/{model}".
    """
    if not model:
        return ModelPricing()
    if provider:
        dyn = _DYNAMIC_PRICING.get(f"{provider}/{model}")
        if dyn is not None:
            return dyn
    if model in _PRICING:
        return _PRICING[model]
    if provider:
        prefixed = f"{provider}/{model}"
        if prefixed in _PRICING:
            return _PRICING[prefixed]
    logger.debug(f"[pricing] no entry for model={model!r} provider={provider!r}")
    return ModelPricing()


def is_loaded() -> bool:
    """True if the pricing file was loaded with at least one entry."""
    return bool(_PRICING)
