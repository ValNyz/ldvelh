"""Central LLM pricing lookup.

Source: litellm's `model_prices_and_context_window.json`, vendored as
`services/model_prices.json`. Refresh periodically:

    curl -fsSL https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json \
        -o backend/services/model_prices.json

The JSON file uses USD per token; we multiply by 1M to match the
ModelPricing schema (USD per million tokens).
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
            input=(input_cost or 0.0) * 1_000_000,
            output=(output_cost or 0.0) * 1_000_000,
            cache_write=(entry.get("cache_creation_input_token_cost") or 0.0) * 1_000_000,
            cache_read=(entry.get("cache_read_input_token_cost") or 0.0) * 1_000_000,
        )
    return result


_PRICING: dict[str, ModelPricing] = _load()


def lookup_pricing(model: str, provider: str | None = None) -> ModelPricing:
    """Return USD-per-million-token rates for a model.

    Tries `model` directly first, then `{provider}/{model}` (litellm uses
    a provider prefix for some entries, e.g. "mistral/mistral-large-latest").
    Returns zero-rate pricing if the model isn't found (caller can decide
    to surface tokens-only).
    """
    if not model:
        return ModelPricing()
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
