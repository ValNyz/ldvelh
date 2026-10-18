"""LLM model catalog: reads the llm_models table into an immutable, cached ModelCatalog."""

import json
import logging
import time
from dataclasses import dataclass

from config import get_settings
from llm.profile import ModelProfile
from services.pricing import ModelPricing, register_pricing
from utils.log_safe import log_cause

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogEntry:
    provider: str
    model_id: str
    label: str
    status: str
    roles: tuple[str, ...]
    default_rank: int | None
    prices: ModelPricing | None
    profile: ModelProfile | None  # None = no specific rules (provider fallback applies)


def _sort_key(e: CatalogEntry):
    return (e.default_rank is None, e.default_rank or 0, e.model_id)


class ModelCatalog:
    def __init__(self, entries: list[CatalogEntry]):
        self._entries = {(e.provider, e.model_id): e for e in entries}

    def is_empty(self) -> bool:
        return not self._entries

    def enabled(self, provider: str) -> list[CatalogEntry]:
        found = [e for e in self._entries.values() if e.provider == provider and e.status == "enabled"]
        return sorted(found, key=_sort_key)

    def entry(self, provider: str, model_id: str) -> CatalogEntry | None:
        return self._entries.get((provider, model_id))

    def default_model(self, provider: str, role: str) -> str | None:
        for e in self.enabled(provider):
            if role in e.roles:
                return e.model_id
        return None

    def profile(self, provider: str, model_id: str) -> ModelProfile | None:
        e = self.entry(provider, model_id)
        return e.profile if e else None


def _as_dict(value) -> dict | None:
    """jsonb arrives as a Python object with the app codec, or as str on a bare connection."""
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else None


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def _row_to_entry(r) -> CatalogEntry:
    prices = None
    if r["input_price"] is not None or r["output_price"] is not None:
        prices = ModelPricing(
            _num(r["input_price"]), _num(r["output_price"]),
            _num(r["cache_write_price"]), _num(r["cache_read_price"]),
        )
    profile_data = _as_dict(r["profile"])
    return CatalogEntry(
        provider=r["provider"],
        model_id=r["model_id"],
        label=r["label"],
        status=r["status"],
        roles=tuple(r["roles"] or ()),
        default_rank=r["default_rank"],
        prices=prices,
        profile=ModelProfile.from_dict(profile_data) if profile_data else None,
    )


_cache: tuple[ModelCatalog, float] | None = None


def invalidate_catalog_cache() -> None:
    global _cache
    _cache = None


async def load_catalog(pool, *, ttl_seconds: int = 600) -> ModelCatalog:
    """Return the catalog, cached for ttl_seconds. On DB error: last good value, else empty."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[1] < ttl_seconds:
        return _cache[0]
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT provider, model_id, label, status, roles, default_rank,
                          input_price, output_price, cache_write_price, cache_read_price, profile
                   FROM llm_models"""
            )
        entries = [_row_to_entry(r) for r in rows]
    except Exception as e:
        log_cause(logger, logging.WARNING, "[llm_models] catalog load failed, using fallback", e,
                  debug_detail=get_settings().log_prompts)
        return _cache[0] if _cache is not None else ModelCatalog([])
    # The usage ledger prices calls with lookup_pricing: register catalog prices there,
    # else a model priced only by the catalog (Nous, models.dev, OpenRouter) costs $0.
    for e in entries:
        if e.prices is not None and (e.prices.input > 0 or e.prices.output > 0):
            register_pricing(e.model_id, e.provider, e.prices)
    catalog = ModelCatalog(entries)
    _cache = (catalog, now)
    return catalog
