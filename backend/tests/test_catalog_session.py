"""LLMSession and /api/providers driven by the llm_models catalog (#70)."""

import pytest
import pytest_asyncio

from llm.profile import ModelProfile
from llm.session import LLMSession, Purpose
from repos.llm_models import CatalogEntry, ModelCatalog, invalidate_catalog_cache
from services.pricing import ModelPricing
from tests.helpers import auth_headers
from tests.test_model_catalog import _insert, llm_table  # noqa: F401  (save/restore fixture)


@pytest.fixture(autouse=True)
def _fresh_cache():
    invalidate_catalog_cache()
    yield
    invalidate_catalog_cache()


def _e(model_id, status="enabled", roles=("narration",), rank=1, profile=None, prices=None):
    return CatalogEntry("mistral", model_id, model_id.upper(), status, tuple(roles), rank,
                        prices, profile)


def test_disabled_user_model_falls_back_to_role_default():
    cat = ModelCatalog([_e("big", roles=("narration",)), _e("off", status="pending", rank=0)])
    s = LLMSession("mistral", "k", user_model="off", catalog=cat)
    assert s.model_for(Purpose.NARRATION) == "big"
    ok = LLMSession("mistral", "k", user_model="big", catalog=cat)
    assert ok.model_for(Purpose.WORLD_GEN) == "big"


def test_mechanical_role_from_catalog():
    cat = ModelCatalog([_e("big"), _e("small", roles=("mechanical",), rank=2)])
    s = LLMSession("mistral", "k", user_model="big", catalog=cat)
    assert s.model_for(Purpose.MECHANICAL) == "small"
    # unlisted purposes: provider default not enabled -> narration default
    assert s.model_for(Purpose.DIRECTOR) == "big"


def test_profile_comes_from_catalog():
    prof = ModelProfile(send_temperature=False)
    cat = ModelCatalog([_e("big", profile=prof)])
    s = LLMSession("mistral", "k", user_model="big", catalog=cat)
    assert s.provider_for(Purpose.NARRATION).profile == prof


@pytest.mark.parametrize("catalog", [None, ModelCatalog([])])
def test_empty_catalog_falls_back_to_provider_constants(catalog):
    s = LLMSession("anthropic", "k", user_model="claude-sonnet-5-5", catalog=catalog)
    assert s.model_for(Purpose.NARRATION) == "claude-sonnet-5-5"
    assert s.model_for(Purpose.MECHANICAL) == "claude-haiku-5-5"
    assert s.model_for(Purpose.RESOLVER) == "claude-sonnet-5-5"
    m = LLMSession("mistral", "k", user_model="mistral-small-latest", catalog=catalog)
    assert m.model_for(Purpose.MECHANICAL) == "mistral-small-latest"
    assert m.model_for(Purpose.DIRECTOR) == "mistral-large-latest"


async def test_providers_catalog_lists_only_enabled_models():
    from services.llm_providers import get_provider_catalog_async

    cat = ModelCatalog([
        CatalogEntry("anthropic", "claude-sonnet-5-5", "S", "enabled", ("narration",), 1,
                     ModelPricing(3, 15, 0, 0), None),
        CatalogEntry("anthropic", "claude-opus-5-5", "O", "pending", (), 2,
                     ModelPricing(5, 25, 0, 0), None),
    ])
    data = await get_provider_catalog_async({}, catalog=cat)
    a = data["providers"]["anthropic"]
    assert [m["id"] for m in a["models"]] == ["claude-sonnet-5-5"]
    assert a["models"][0]["input_price"] == 3
    assert a["default_model"] == "claude-sonnet-5-5"


async def test_providers_endpoint_lists_only_enabled_models(client, test_user, llm_table):  # noqa: F811
    await _insert(llm_table, "claude-sonnet-5-5", provider="anthropic", label="S",
                  roles=["narration"], rank=1, inp=3, out=15)
    await _insert(llm_table, "claude-opus-5-5", provider="anthropic", label="O",
                  status="pending", rank=2, inp=5, out=25)
    r = await client.get("/api/providers", headers=auth_headers(test_user["token"]))
    a = r.json()["providers"]["anthropic"]
    assert [m["id"] for m in a["models"]] == ["claude-sonnet-5-5"]
    assert a["default_model"] == "claude-sonnet-5-5"


async def test_providers_endpoint_survives_catalog_db_error(client, test_user, monkeypatch):
    import api.routes as routes
    from repos.llm_models import load_catalog

    class Broken:
        def acquire(self):
            raise OSError("db down")

    async def broken_load(pool):
        return await load_catalog(Broken())

    monkeypatch.setattr(routes, "load_catalog", broken_load)
    r = await client.get("/api/providers", headers=auth_headers(test_user["token"]))
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["providers"]["anthropic"]["models"]]
    assert "claude-sonnet-5-5" in ids and "claude-opus-5-5" in ids  # hard-coded list


def test_other_provider_only_catalog_keeps_old_path():
    cat = ModelCatalog([_e("big")])  # mistral rows only
    s = LLMSession("anthropic", "k", user_model="claude-sonnet-5-5", catalog=cat)
    assert s.model_for(Purpose.MECHANICAL) == "claude-haiku-5-5"
    assert s.model_for(Purpose.RESOLVER) == "claude-sonnet-5-5"


def _a(model_id, profile=None, roles=("narration",), status="enabled", rank=1):
    return CatalogEntry("anthropic", model_id, model_id, status, tuple(roles), rank, None, profile)


def test_admin_profile_reaches_default_model_purposes():
    prof = ModelProfile(send_temperature=False, thinking_headroom=7)
    cat = ModelCatalog([_a("claude-sonnet-5-5", prof)])
    s = LLMSession("anthropic", "k", user_model="claude-sonnet-5-5", catalog=cat)
    assert s.provider_for(Purpose.EXTRACTION).profile == prof
    assert s.provider_for(Purpose.RESOLVER).profile == prof


def test_enabled_entry_without_profile_passes_none(monkeypatch):
    import llm.session as sess
    seen = []
    real = sess.get_provider
    monkeypatch.setattr(sess, "get_provider",
                        lambda *a, **kw: (seen.append(kw.get("profile", "absent")), real(*a, **kw))[1])
    cat = ModelCatalog([_a("claude-sonnet-5-5")])
    LLMSession("anthropic", "k", catalog=cat).provider_for(Purpose.NARRATION)
    assert seen[-1] is None


def test_user_model_not_enabled_is_dropped_without_narration_holder():
    cat = ModelCatalog([_e("big", roles=("mechanical",)), _e("off", status="pending")])
    s = LLMSession("mistral", "k", user_model="off", catalog=cat)
    assert s.model_for(Purpose.NARRATION) == "mistral-large-latest"  # provider default
    ok = LLMSession("mistral", "k", user_model="big", catalog=cat)
    assert ok.model_for(Purpose.NARRATION) == "big"


async def test_unknown_anthropic_model_without_profile_hidden():
    from services.llm_providers import get_provider_catalog_async

    cat = ModelCatalog([_a("claude-sonnet-5-5"), _a("claude-new-9", roles=()),
                        _a("claude-new-8", ModelProfile(send_temperature=False), roles=())])
    cat = ModelCatalog([CatalogEntry(e.provider, e.model_id, e.label, e.status, e.roles,
                                     e.default_rank, ModelPricing(1, 2, 0, 0), e.profile)
                        for e in (cat.entry("anthropic", m) for m in
                                  ("claude-sonnet-5-5", "claude-new-9", "claude-new-8"))])
    data = await get_provider_catalog_async({}, catalog=cat)
    ids = [m["id"] for m in data["providers"]["anthropic"]["models"]]
    assert "claude-new-9" not in ids and "claude-new-8" in ids


# --- Final review fixes ------------------------------------------------------

def test_anthropic_mechanical_follows_catalog_model():
    """With a catalog profile the instance runs MODEL_MAIN for every purpose (logs, ledger)."""
    from services.llm_providers import AnthropicProvider

    prof = AnthropicProvider.FALLBACK_PROFILES["claude-sonnet-5-5"]
    p = AnthropicProvider(api_key="k", model="claude-sonnet-5-5", profile=prof)
    assert p.model_name("mechanical") == "claude-sonnet-5-5"
    # Without a catalog profile: unchanged (Haiku for the mechanical tier).
    assert AnthropicProvider(api_key="k", model="claude-sonnet-5-5").model_name("mechanical") \
        == "claude-haiku-5-5"
    cat = ModelCatalog([CatalogEntry("anthropic", "claude-sonnet-5-5", "S", "enabled",
                                     ("narration", "mechanical"), 1, None, prof)])
    s = LLMSession("anthropic", "k", user_model="claude-sonnet-5-5", catalog=cat)
    assert s.model_for(Purpose.MECHANICAL) == "claude-sonnet-5-5"
