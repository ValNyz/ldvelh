"""Tests for the llm_models catalog reader (repos/llm_models.py)."""

import json

import pytest

from llm.profile import ModelProfile
from repos import llm_models
from repos.llm_models import CatalogEntry, ModelCatalog, invalidate_catalog_cache, load_catalog
from services.pricing import ModelPricing
from tests.helpers import insert_llm_model


@pytest.fixture(autouse=True)
def _fresh_cache():
    invalidate_catalog_cache()
    yield
    invalidate_catalog_cache()


def _entry(model_id, status="enabled", roles=("narration",), rank=None, provider="p", profile=None):
    return CatalogEntry(provider, model_id, model_id, status, tuple(roles), rank, None, profile)


def test_enabled_filters_and_sorts():
    cat = ModelCatalog([
        _entry("b", rank=2),
        _entry("a", rank=2),
        _entry("c", rank=1),
        _entry("off", status="pending", rank=0),
        _entry("other", provider="q"),
    ])
    assert [e.model_id for e in cat.enabled("p")] == ["c", "a", "b"]
    assert cat.entry("p", "off").status == "pending"
    assert cat.entry("p", "nope") is None
    assert not cat.is_empty()
    assert ModelCatalog([]).is_empty()


def test_default_model_only_enabled_and_by_rank():
    cat = ModelCatalog([
        _entry("pend", status="pending", rank=0, roles=("narration",)),
        _entry("z", rank=1, roles=("narration",)),
        _entry("a", rank=5, roles=("narration", "mechanical")),
        _entry("m", rank=3, roles=("mechanical",)),
    ])
    assert cat.default_model("p", "narration") == "z"
    assert cat.default_model("p", "mechanical") == "m"
    assert cat.default_model("p", "other") is None
    assert cat.default_model("zz", "narration") is None


def test_profile_lookup():
    prof = ModelProfile(send_temperature=False)
    cat = ModelCatalog([_entry("a", profile=prof), _entry("b")])
    assert cat.profile("p", "a") == prof
    assert cat.profile("p", "b") is None
    assert cat.profile("p", "missing") is None


@pytest.mark.asyncio
async def test_load_reads_rows(llm_table):
    await insert_llm_model(llm_table, "m1", rank=1, inp=3, out=15, cw=3.75, cr=0.3,
                  profile={"send_temperature": False})
    await insert_llm_model(llm_table, "m2", inp=None, out=None)
    cat = await load_catalog(llm_table)
    m1, m2 = cat.entry("p", "m1"), cat.entry("p", "m2")
    assert m1.prices == ModelPricing(3, 15, 3.75, 0.3)
    assert m1.profile == ModelProfile(send_temperature=False)
    assert m1.roles == ("narration",) and m1.default_rank == 1
    assert m2.prices is None and m2.profile is None


@pytest.mark.asyncio
async def test_load_handles_jsonb_as_str():
    class Conn:
        async def fetch(self, q):
            return [{"provider": "p", "model_id": "m", "label": "m", "status": "enabled",
                     "roles": ["narration"], "default_rank": None, "input_price": None,
                     "output_price": None, "cache_write_price": None, "cache_read_price": None,
                     "profile": json.dumps({"force_tool": False})}]

    class Acq:
        async def __aenter__(self): return Conn()
        async def __aexit__(self, *a): return False

    class Pool:
        def acquire(self): return Acq()

    cat = await load_catalog(Pool())
    assert cat.profile("p", "m") == ModelProfile(force_tool=False)


class _CountingPool:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def acquire(self):
        pool = self

        class Acq:
            async def __aenter__(self):
                pool.calls += 1
                if pool.fail:
                    raise OSError("db down")
                return self

            async def fetch(self, q):
                return [{"provider": "p", "model_id": "m", "label": "m", "status": "enabled",
                         "roles": [], "default_rank": None, "input_price": None,
                         "output_price": None, "cache_write_price": None,
                         "cache_read_price": None, "profile": None}]

            async def __aexit__(self, *a):
                return False

        return Acq()


@pytest.mark.asyncio
async def test_load_is_cached():
    pool = _CountingPool()
    a = await load_catalog(pool)
    b = await load_catalog(pool)
    assert a is b and pool.calls == 1
    invalidate_catalog_cache()
    await load_catalog(pool)
    assert pool.calls == 2


@pytest.mark.asyncio
async def test_ttl_expiry_reloads():
    pool = _CountingPool()
    await load_catalog(pool, ttl_seconds=0)
    await load_catalog(pool, ttl_seconds=0)
    assert pool.calls == 2


@pytest.mark.asyncio
async def test_db_error_returns_empty_then_last_good(caplog):
    bad = _CountingPool(fail=True)
    assert (await load_catalog(bad)).is_empty()
    assert "llm_models" in caplog.text
    good = _CountingPool()
    cat = await load_catalog(good)
    assert not cat.is_empty()
    # expire the cache, then fail: last good catalog survives
    cat2 = await load_catalog(bad, ttl_seconds=0)
    assert cat2 is cat


# --- Final review fixes ------------------------------------------------------

@pytest.mark.asyncio
async def test_load_registers_catalog_prices_for_cost_tracking(monkeypatch):
    """Catalog prices feed call_cost: a model priced only by the catalog is never $0."""
    from llm.usage import call_cost
    from services import pricing
    from services.llm_providers import LLMUsage

    monkeypatch.setattr(pricing, "_DYNAMIC_PRICING", {})

    class Acq:
        async def __aenter__(self):
            return self

        async def fetch(self, q):
            base = {"provider": "nous", "label": "x", "status": "enabled", "roles": [],
                    "default_rank": None, "cache_write_price": None, "cache_read_price": None,
                    "profile": None}
            return [{**base, "model_id": "zz-priced", "input_price": 1, "output_price": 3},
                    {**base, "model_id": "zz-unpriced", "input_price": None, "output_price": None}]

        async def __aexit__(self, *a):
            return False

    class Pool:
        def acquire(self):
            return Acq()

    await load_catalog(Pool())
    usage = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert call_cost(usage, "nous", "zz-priced") == pytest.approx(4.0)
    assert "nous/zz-unpriced" not in pricing._DYNAMIC_PRICING
