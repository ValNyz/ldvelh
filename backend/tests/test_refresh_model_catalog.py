"""Model catalog refresh command (scripts/refresh_model_catalog.py).

A fake lister, fake prober and fake price sources stand in for the network:
no real LLM call is ever made here. The llm_models seed rows are restored
after each test.
"""

import logging
from types import SimpleNamespace

import pytest
import pytest_asyncio

from llm.profile import ModelProfile
from scripts import refresh_model_catalog as refresh
from scripts.refresh_model_catalog import PriceSources, refresh_provider
from scripts.smoke_providers import ProbeResult
from services.llm_providers import AnthropicProvider


@pytest_asyncio.fixture
async def conn(test_pool):
    """A connection on an empty llm_models; the seed rows come back afterwards."""
    async with test_pool.acquire() as c:
        saved = await c.fetch("SELECT * FROM llm_models")
        await c.execute("DELETE FROM llm_models")
        try:
            yield c
        finally:
            await c.execute("DELETE FROM llm_models")
            for r in saved:
                cols = list(r.keys())
                await c.execute(
                    f"INSERT INTO llm_models ({', '.join(cols)}) VALUES "
                    f"({', '.join(f'${i + 1}' for i in range(len(cols)))})",
                    *[r[col] for col in cols],
                )


async def _insert(c, provider, model_id, **kw):
    await c.execute(
        """INSERT INTO llm_models (provider, model_id, label, status, roles, default_rank,
               input_price, output_price, price_source, profile, source)
           VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
        provider, model_id, kw.get("status", "enabled"), kw.get("roles", []), kw.get("rank"),
        kw.get("inp"), kw.get("out"), kw.get("price_source"), kw.get("profile", {}),
        kw.get("source", "auto"),
    )


async def _row(c, provider, model_id):
    return await c.fetchrow(
        "SELECT * FROM llm_models WHERE provider = $1 AND model_id = $2", provider, model_id)


def _lister(models):
    async def lister(provider_name):
        return [m if isinstance(m, dict) else {"id": m, "label": m} for m in models]
    return lister


def _prober(fail=None, calls=None):
    """All probes pass, except for models in `fail` ({model: detail} or callable)."""
    async def prober(provider_name, model, profile):
        if calls is not None:
            calls.append((model, profile))
        detail = fail(model, profile) if callable(fail) else (fail or {}).get(model)
        if detail:
            return {"stream": ProbeResult(False, detail), "json": ProbeResult(True, "ok"),
                    "structured": ProbeResult(True, "ok")}
        return {name: ProbeResult(True, "ok") for name in ("stream", "json", "structured")}
    return prober


NO_PRICES = PriceSources(models_dev=None, openrouter=None)


async def _refresh(c, provider, models, *, prober=None, auto_enable=True, sources=NO_PRICES,
                   reprobe_all=False, lister=None):
    return await refresh_provider(
        c, provider, "k", auto_enable=auto_enable, reprobe_all=reprobe_all,
        prober=prober or _prober(), price_sources=sources, lister=lister or _lister(models),
    )


PRICED = {"id": "zz-new", "label": "ZZ New", "input_price": 1.0, "output_price": 3.0}


@pytest.mark.asyncio
async def test_new_model_inserted_then_enabled_when_probes_pass(conn):
    report = await _refresh(conn, "mistral", [PRICED, "zz-embed"])
    row = await _row(conn, "mistral", "zz-new")
    assert row["status"] == "enabled" and row["label"] == "ZZ New"
    assert float(row["input_price"]) == 1.0 and float(row["output_price"]) == 3.0
    assert row["price_source"] == "provider"
    assert row["probe_results"]["stream"]["ok"] is True
    assert row["last_probed_at"] is not None
    assert await _row(conn, "mistral", "zz-embed") is None  # not a chat model
    assert report.ok and report.inserted == ["zz-new"]
    # First enabled model of the provider takes both roles.
    assert set(row["roles"]) == {"narration", "mechanical"}


@pytest.mark.asyncio
async def test_anthropic_discovery_stays_pending(conn):
    listed = [{"id": "claude-zz-6", "label": "ZZ 6", "input_price": 2.0, "output_price": 9.0}]
    await _refresh(conn, "anthropic", listed, auto_enable=False)
    row = await _row(conn, "anthropic", "claude-zz-6")
    assert row["status"] == "pending"
    # An unknown Claude id is probed with the Claude 5 rules and keeps them (else it would be hidden).
    fallback = AnthropicProvider.FALLBACK_PROFILES["claude-sonnet-5-5"]
    assert ModelProfile.from_dict(row["profile"]) == fallback


@pytest.mark.asyncio
async def test_failed_probe_records_error(conn):
    await _refresh(conn, "mistral", [PRICED], prober=_prober({"zz-new": "BadRequestError: boom"}))
    row = await _row(conn, "mistral", "zz-new")
    assert row["status"] == "failed"
    assert row["probe_results"]["stream"] == {"ok": False, "detail": "BadRequestError: boom"}
    assert row["roles"] == []


@pytest.mark.asyncio
async def test_temperature_error_retries_without_temperature_and_saves_profile(conn):
    calls = []

    def fail(model, profile):
        if profile is None or profile.send_temperature:
            return "BadRequestError: temperature is not supported for this model"
        return None

    await _refresh(conn, "mistral", [PRICED], prober=_prober(fail, calls))
    row = await _row(conn, "mistral", "zz-new")
    assert row["status"] == "enabled"
    assert ModelProfile.from_dict(row["profile"]) == ModelProfile(send_temperature=False)
    assert len(calls) == 2 and calls[0][1] is None


@pytest.mark.asyncio
async def test_dead_default_is_replaced_by_preferred_enabled_model(conn, caplog):
    await _insert(conn, "mistral", "dead", roles=["narration", "mechanical"], rank=1, inp=1, out=1,
                  price_source="code")
    await _insert(conn, "mistral", "cheap", rank=None, inp=0.1, out=0.1, price_source="code")
    await _insert(conn, "mistral", "second", rank=2, inp=5, out=5, price_source="code")
    await _insert(conn, "mistral", "third", rank=3, inp=5, out=5, price_source="code")
    with caplog.at_level(logging.WARNING):
        report = await _refresh(conn, "mistral", ["dead", "cheap", "second", "third"],
                                prober=_prober({"dead": "APIError: 500"}))
    dead, second = await _row(conn, "mistral", "dead"), await _row(conn, "mistral", "second")
    assert dead["status"] == "failed" and dead["roles"] == []
    assert set(second["roles"]) == {"narration", "mechanical"}
    assert "[catalog] mistral: narration moved to second" in caplog.text
    assert report.ok


@pytest.mark.asyncio
async def test_listing_failure_does_not_retire_models(conn):
    await _insert(conn, "mistral", "keep", roles=["narration"], inp=1, out=1, price_source="code")

    async def broken(provider_name):
        raise RuntimeError("503")

    report = await _refresh(conn, "mistral", [], lister=broken)
    assert report.error and not report.ok
    assert (await _row(conn, "mistral", "keep"))["status"] == "enabled"
    # An empty listing is a failure too: never retire everything on a blip.
    report = await _refresh(conn, "mistral", [])
    assert not report.ok
    assert (await _row(conn, "mistral", "keep"))["status"] == "enabled"


@pytest.mark.asyncio
async def test_auto_model_absent_from_listing_is_retired(conn):
    await _insert(conn, "mistral", "gone", inp=1, out=1, price_source="code")
    await _insert(conn, "mistral", "gone-manual", inp=1, out=1, price_source="code", source="manual")
    await _refresh(conn, "mistral", [PRICED])
    assert (await _row(conn, "mistral", "gone"))["status"] == "retired"
    assert (await _row(conn, "mistral", "gone-manual"))["status"] == "enabled"


@pytest.mark.asyncio
async def test_manual_rows_keep_status(conn):
    await _insert(conn, "mistral", "man-pending", status="pending", source="manual", inp=1, out=1,
                  price_source="code")
    await _insert(conn, "mistral", "man-enabled", status="enabled", source="manual",
                  roles=["narration", "mechanical"], inp=1, out=1, price_source="code")
    await _refresh(conn, "mistral", ["man-pending", "man-enabled"],
                   prober=_prober({"man-enabled": "BadRequestError: temperature"}))
    pending, enabled = await _row(conn, "mistral", "man-pending"), await _row(conn, "mistral", "man-enabled")
    assert pending["status"] == "pending" and pending["probe_results"]["stream"]["ok"]
    assert enabled["status"] == "enabled" and not enabled["probe_results"]["stream"]["ok"]
    assert enabled["profile"] == {}  # manual profile untouched


@pytest.mark.asyncio
async def test_unpriced_model_not_enabled(conn):
    await _refresh(conn, "mistral", ["zz-unpriced"])
    row = await _row(conn, "mistral", "zz-unpriced")
    assert row["status"] == "pending"
    assert row["input_price"] is None and row["price_source"] is None


@pytest.mark.asyncio
async def test_price_from_models_dev_when_no_code_price(conn):
    sources = PriceSources(
        models_dev={"mistral": {"models": {"zz-md": {"cost": {
            "input": 0.4, "output": 2, "cache_read": 0.04, "tiers": [{"x": 1}]}}}}},
        openrouter=None)
    await _refresh(conn, "mistral", ["zz-md"], sources=sources)
    row = await _row(conn, "mistral", "zz-md")
    assert row["price_source"] == "models.dev" and row["status"] == "enabled"
    assert float(row["input_price"]) == 0.4 and float(row["cache_read_price"]) == 0.04


@pytest.mark.asyncio
async def test_code_price_wins_over_models_dev(conn):
    sources = PriceSources(models_dev={"anthropic": {"models": {"claude-haiku-5-5": {
        "cost": {"input": 99, "output": 99}}}}}, openrouter=None)
    await _insert(conn, "anthropic", "claude-haiku-5-5", source="manual", roles=["mechanical"])
    await _refresh(conn, "anthropic", ["claude-haiku-5-5"], sources=sources, auto_enable=False)
    row = await _row(conn, "anthropic", "claude-haiku-5-5")
    assert row["price_source"] == "code" and float(row["output_price"]) == 0.5


@pytest.mark.asyncio
async def test_openrouter_estimate_for_nous(conn, caplog):
    sources = PriceSources(
        models_dev={"mistral": {"models": {}}},
        openrouter={"data": [{"id": "NousResearch/Hermes-ZZ", "pricing": {
            "prompt": "0.000001", "completion": "0.000003", "input_cache_read": "0.0000001"}}]})
    with caplog.at_level(logging.INFO):
        await _refresh(conn, "nous", ["hermes-zz"], sources=sources)
    row = await _row(conn, "nous", "hermes-zz")
    assert row["price_source"] == "openrouter"
    assert float(row["input_price"]) == pytest.approx(1.0) and float(row["output_price"]) == pytest.approx(3.0)
    assert "estimate" in caplog.text
    # Providers with a models.dev entry never use the OpenRouter estimate.
    await _refresh(conn, "mistral", ["NousResearch/Hermes-ZZ"], sources=sources)
    assert (await _row(conn, "mistral", "NousResearch/Hermes-ZZ"))["price_source"] is None


@pytest.mark.asyncio
async def test_manual_price_never_overwritten(conn):
    await _insert(conn, "mistral", "zz-new", inp=7, out=7, price_source="manual")
    await _refresh(conn, "mistral", [PRICED])
    row = await _row(conn, "mistral", "zz-new")
    assert row["price_source"] == "manual" and float(row["output_price"]) == 7


@pytest.mark.asyncio
async def test_big_price_change_is_logged_and_applied(conn, caplog):
    await _insert(conn, "mistral", "zz-new", inp=1, out=1, price_source="provider")
    with caplog.at_level(logging.WARNING):
        await _refresh(conn, "mistral", [PRICED])
    assert float((await _row(conn, "mistral", "zz-new"))["output_price"]) == 3
    assert "[catalog] mistral/zz-new: price change" in caplog.text


@pytest.mark.asyncio
async def test_price_source_down_does_not_fail_refresh(conn, caplog):
    async def fetch(url):
        if "models.dev" in url:
            raise TimeoutError("timed out")
        return {"unexpected": True}

    with caplog.at_level(logging.WARNING):
        sources = await refresh.fetch_price_sources(fetch)
    assert sources.models_dev is None and sources.openrouter is None
    assert "[catalog] price source models.dev unavailable" in caplog.text
    assert "[catalog] price source openrouter unavailable" in caplog.text
    report = await _refresh(conn, "mistral", [PRICED], sources=sources)
    assert report.ok and (await _row(conn, "mistral", "zz-new"))["status"] == "enabled"


@pytest.mark.asyncio
async def test_role_without_enabled_model_fails_the_run(conn):
    await _insert(conn, "mistral", "only", roles=["narration", "mechanical"], inp=1, out=1,
                  price_source="code")
    report = await _refresh(conn, "mistral", ["only"], prober=_prober({"only": "APIError: 500"}))
    assert not report.ok and set(report.roles_lost) == {"narration", "mechanical"}
    # The dead holder keeps its roles so it takes them back once it recovers.
    assert set((await _row(conn, "mistral", "only"))["roles"]) == {"narration", "mechanical"}


@pytest.mark.asyncio
async def test_probe_selection(conn):
    await _insert(conn, "mistral", "healthy-norole", inp=1, out=1, price_source="code")
    await _insert(conn, "mistral", "holder", roles=["narration", "mechanical"], inp=1, out=1,
                  price_source="code")
    await _insert(conn, "mistral", "was-failed", status="failed", inp=1, out=1, price_source="code")
    calls = []
    await _refresh(conn, "mistral", ["healthy-norole", "holder", "was-failed"],
                   prober=_prober(calls=calls))
    assert sorted(m for m, _ in calls) == ["holder", "was-failed"]
    assert (await _row(conn, "mistral", "was-failed"))["status"] == "enabled"
    calls.clear()
    await _refresh(conn, "mistral", ["healthy-norole", "holder", "was-failed"],
                   prober=_prober(calls=calls), reprobe_all=True)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(conn):
    await refresh_provider(conn, "mistral", "k", auto_enable=True, reprobe_all=False,
                           prober=_prober(), price_sources=NO_PRICES, lister=_lister([PRICED]),
                           dry_run=True)
    assert await _row(conn, "mistral", "zz-new") is None


def _settings(**kw):
    base = {f: "" for f in refresh.KEY_FIELDS.values()}
    base.update(catalog_keys_user_email="", catalog_auto_enable="mistral",
                database_url="postgresql://unused")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_refresh_without_keys_changes_nothing(conn, monkeypatch, capsys):
    before = await conn.fetchval("SELECT count(*) FROM llm_models")
    monkeypatch.setattr(refresh, "get_settings", lambda: _settings())

    async def no_connect(*a, **k):
        raise AssertionError("must not touch the database")

    monkeypatch.setattr(refresh, "_connect", no_connect)
    assert await refresh.main([]) == 1
    assert await conn.fetchval("SELECT count(*) FROM llm_models") == before
    assert "no API key" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_main_runs_refresh_and_reports_exit_code(conn, monkeypatch):
    monkeypatch.setattr(refresh, "get_settings", lambda: _settings(mistral_api_key="sk-x"))

    async def same_conn(url):
        return conn

    async def no_close(c):
        return None

    async def sources(fetch=None):
        return NO_PRICES

    monkeypatch.setattr(refresh, "_connect", same_conn)
    monkeypatch.setattr(refresh, "_close", no_close)
    monkeypatch.setattr(refresh, "fetch_price_sources", sources)
    monkeypatch.setattr(refresh, "live_lister", lambda name, key: _lister([PRICED]))
    monkeypatch.setattr(refresh, "live_prober", lambda key: _prober())
    assert await refresh.main(["--provider", "mistral"]) == 0
    assert (await _row(conn, "mistral", "zz-new"))["status"] == "enabled"


@pytest.mark.asyncio
async def test_manual_actions(conn, monkeypatch):
    async def same_conn(url):
        return conn

    async def no_close(c):
        return None

    monkeypatch.setattr(refresh, "get_settings", lambda: _settings())
    monkeypatch.setattr(refresh, "_connect", same_conn)
    monkeypatch.setattr(refresh, "_close", no_close)
    await _insert(conn, "mistral", "a", roles=["narration"], status="pending")
    await _insert(conn, "mistral", "b", status="pending")
    assert await refresh.main(["--enable", "mistral", "b"]) == 0
    assert await refresh.main(["--set-role", "mistral", "b", "narration"]) == 0
    a, b = await _row(conn, "mistral", "a"), await _row(conn, "mistral", "b")
    assert b["status"] == "enabled" and b["source"] == "manual" and b["roles"] == ["narration"]
    assert a["roles"] == []
    assert await refresh.main(["--disable", "mistral", "b"]) == 0
    assert (await _row(conn, "mistral", "b"))["status"] == "retired"
    assert await refresh.main(["--disable", "mistral", "missing"]) == 1
    assert await refresh.main(["--set-role", "mistral", "a", "bogus"]) == 1
