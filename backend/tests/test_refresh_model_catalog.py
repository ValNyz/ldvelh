"""Model catalog refresh command (scripts/refresh_model_catalog.py).

A fake lister, fake prober and fake price sources stand in for the network:
no real LLM call is ever made here. The llm_models seed rows are restored
after each test.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest
import pytest_asyncio

from llm.profile import ModelProfile
from scripts import refresh_model_catalog as refresh
from scripts.refresh_model_catalog import PriceSources, RefreshReport, refresh_provider
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
                                prober=_prober({"dead": "NotFoundError: Error code: 404 - model_not_found"}))
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
    await _insert(conn, "mistral", "gone", status="pending", inp=1, out=1, price_source="code")
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
    report = await _refresh(conn, "mistral", ["only"], prober=_prober({"only": "NotFoundError: Error code: 404 - model_not_found"}))
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
    # Optional roles (no automatic holder): the identity resolver's models.
    assert await refresh.main(["--set-role", "mistral", "a", "identity"]) == 0
    assert await refresh.main(["--set-role", "mistral", "b", "identity_strong"]) == 0
    a, b = await _row(conn, "mistral", "a"), await _row(conn, "mistral", "b")
    assert a["roles"] == ["identity"] and b["roles"] == ["narration", "identity_strong"]


# --- Fix round 1: transient failures never drop a working model -------------

async def _holder(c, model_id="holder", **kw):
    await _insert(c, "mistral", model_id, roles=["narration", "mechanical"], rank=1, inp=1, out=1,
                  price_source="code", **kw)


@pytest.mark.asyncio
async def test_role_holder_transient_failure_stays_enabled_then_recovers(conn):
    await _holder(conn)
    await _insert(conn, "mistral", "backup", rank=2, inp=1, out=1, price_source="code")
    await _refresh(conn, "mistral", ["holder", "backup"],
                   prober=_prober({"holder": "RateLimitError: Error code: 429"}))
    row = await _row(conn, "mistral", "holder")
    assert row["status"] == "enabled" and set(row["roles"]) == {"narration", "mechanical"}
    assert row["probe_results"]["failures"] == 1 and not row["probe_results"]["stream"]["ok"]
    await _refresh(conn, "mistral", ["holder", "backup"])
    row = await _row(conn, "mistral", "holder")
    assert row["status"] == "enabled" and row["probe_results"]["failures"] == 0


@pytest.mark.asyncio
async def test_three_consecutive_failures_demote_and_move_role(conn):
    await _holder(conn)
    await _insert(conn, "mistral", "backup", rank=2, inp=1, out=1, price_source="code")
    for run in range(3):
        await _refresh(conn, "mistral", ["holder", "backup"],
                       prober=_prober({"holder": "APIError: Error code: 503"}))
        row = await _row(conn, "mistral", "holder")
        assert row["status"] == ("failed" if run == 2 else "enabled")
    assert row["roles"] == [] and row["probe_results"]["was_enabled"] is True
    assert set((await _row(conn, "mistral", "backup"))["roles"]) == {"narration", "mechanical"}


@pytest.mark.asyncio
async def test_not_found_demotes_immediately(conn):
    await _holder(conn)
    await _insert(conn, "mistral", "backup", rank=2, inp=1, out=1, price_source="code")
    await _refresh(conn, "mistral", ["holder", "backup"],
                   prober=_prober({"holder": "NotFoundError: Error code: 404 - not found"}))
    row = await _row(conn, "mistral", "holder")
    assert row["status"] == "failed" and row["roles"] == []


@pytest.mark.asyncio
async def test_role_holder_absent_three_times_is_retired(conn):
    await _holder(conn)
    await _insert(conn, "mistral", "backup", rank=2, inp=1, out=1, price_source="code")
    for run in range(3):
        await _refresh(conn, "mistral", ["backup"])
        row = await _row(conn, "mistral", "holder")
        assert row["status"] == ("retired" if run == 2 else "enabled")
        if run < 2:
            assert set(row["roles"]) == {"narration", "mechanical"}
            assert row["probe_results"]["absent"] == run + 1
    assert set((await _row(conn, "mistral", "backup"))["roles"]) == {"narration", "mechanical"}
    # Listed again: the absence counter of a surviving row resets.
    await _insert(conn, "mistral", "flaky", inp=1, out=1, price_source="code")
    await _refresh(conn, "mistral", ["backup"])
    await _refresh(conn, "mistral", ["backup", "flaky"])
    assert (await _row(conn, "mistral", "flaky"))["probe_results"]["absent"] == 0


@pytest.mark.asyncio
async def test_exception_in_one_provider_still_processes_the_next(conn, monkeypatch):
    monkeypatch.setattr(refresh, "get_settings",
                        lambda: _settings(mistral_api_key="sk-a", nous_api_key="sk-b",
                                          catalog_auto_enable="mistral,nous"))

    async def same_conn(url):
        return conn

    async def no_close(c):
        return None

    async def sources(fetch=None):
        return NO_PRICES

    async def boom(name, model, profile):
        raise RuntimeError("prober crashed")

    monkeypatch.setattr(refresh, "_connect", same_conn)
    monkeypatch.setattr(refresh, "_close", no_close)
    monkeypatch.setattr(refresh, "fetch_price_sources", sources)
    monkeypatch.setattr(refresh, "live_lister", lambda name, key: _lister([PRICED]))
    monkeypatch.setattr(refresh, "live_prober", lambda key: boom if key == "sk-a" else _prober())
    assert await refresh.main(["--provider", "mistral", "--provider", "nous"]) == 1
    assert await _row(conn, "mistral", "zz-new") is None  # rolled back
    assert (await _row(conn, "nous", "zz-new"))["status"] == "enabled"


@pytest.mark.asyncio
async def test_manual_retired_row_not_probed(conn):
    await _insert(conn, "mistral", "off", status="retired", source="manual", inp=1, out=1,
                  price_source="code")
    calls = []
    await _refresh(conn, "mistral", ["off"], prober=_prober(calls=calls), reprobe_all=True)
    assert calls == [] and (await _row(conn, "mistral", "off"))["status"] == "retired"


@pytest.mark.asyncio
async def test_recovered_previously_enabled_row_is_re_enabled_without_auto_enable(conn):
    await _holder(conn)
    await _refresh(conn, "mistral", ["holder"], auto_enable=False,
                   prober=_prober({"holder": "NotFoundError: Error code: 404"}))
    assert (await _row(conn, "mistral", "holder"))["status"] == "failed"
    await _refresh(conn, "mistral", ["holder"], auto_enable=False)
    row = await _row(conn, "mistral", "holder")
    assert row["status"] == "enabled" and row["probe_results"].get("was_enabled") is not True


@pytest.mark.asyncio
async def test_retry_starts_from_provider_fallback_profile(conn):
    calls = []
    fail = lambda model, profile: "BadRequestError: temperature is deprecated" \
        if profile is None else None
    await _refresh(conn, "anthropic", [{"id": "claude-haiku-5-5"}], prober=_prober(fail, calls),
                   auto_enable=False)
    # Any retry keeps Haiku's built-in rules (thinking disabled), never DEFAULT_PROFILE's.
    haiku = AnthropicProvider.FALLBACK_PROFILES["claude-haiku-5-5"]
    assert all(p is None or p.thinking == haiku.thinking for _, p in calls)


@pytest.mark.asyncio
async def test_set_role_keeps_source(conn, monkeypatch):
    async def same_conn(url):
        return conn

    async def no_close(c):
        return None

    monkeypatch.setattr(refresh, "get_settings", lambda: _settings())
    monkeypatch.setattr(refresh, "_connect", same_conn)
    monkeypatch.setattr(refresh, "_close", no_close)
    await _insert(conn, "mistral", "a", source="auto")
    assert await refresh.main(["--set-role", "mistral", "a", "mechanical"]) == 0
    row = await _row(conn, "mistral", "a")
    assert row["source"] == "auto" and row["roles"] == ["mechanical"]


@pytest.mark.parametrize("detail,permanent", [
    ("NotFoundError: Error code: 404 - model gone", True),
    ("BadRequestError: invalid model id", True),
    ("RateLimitError: Error code: 429 (request id req_4040a)", False),
    ("APITimeoutError: timeout after 404 ms", False),
])
def test_permanent_error_detection_ignores_stray_404(detail, permanent):
    results = {"stream": ProbeResult(False, detail)}
    assert refresh._is_permanent(results) is permanent


# --- Final review fixes ------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 1e5, 1234567.0])
def test_invalid_source_price_is_ignored(bad, caplog):
    sources = PriceSources(models_dev={"mistral": {"models": {"zz": {"cost": {
        "input": bad, "output": 2}}}}}, openrouter=None)
    with caplog.at_level(logging.WARNING):
        assert sources.from_models_dev("mistral", "zz") is None
    assert "invalid price" in caplog.text
    # Listing first: an invalid listing price falls through to the next source.
    listed = {"id": "zz", "input_price": str(bad), "output_price": 1}
    found = refresh.resolve_price("mistral", "zz", listed, PriceSources(
        models_dev={"mistral": {"models": {"zz": {"cost": {"input": 0.4, "output": 2}}}}},
        openrouter=None))
    assert found[1] == "models.dev" and found[0].input == 0.4


def test_openrouter_invalid_price_is_ignored():
    sources = PriceSources(models_dev=None, openrouter={"data": [
        {"id": "zz", "pricing": {"prompt": "Infinity", "completion": "0.000001"}}]})
    assert sources.from_openrouter("zz") is None


def test_prices_rounded_to_db_precision():
    sources = PriceSources(models_dev=None, openrouter={"data": [
        {"id": "zz", "pricing": {"prompt": "0.0000001", "completion": "0.0000007"}}]})
    price, _ = refresh.resolve_price("nous", "zz", None, sources)
    assert price.input == 0.1 and price.output == 0.7


@pytest.mark.asyncio
async def test_unchanged_float_price_does_not_rewrite_row(conn):
    sources = PriceSources(models_dev=None, openrouter={"data": [
        {"id": "zz-or", "pricing": {"prompt": "0.0000001", "completion": "0.0000007"}}]})
    await _holder(conn)
    await conn.execute("UPDATE llm_models SET provider = 'nous' WHERE model_id = 'holder'")
    await _insert(conn, "nous", "zz-or", inp=0.1, out=0.7, price_source="openrouter")
    await conn.execute("UPDATE llm_models SET cache_write_price = 0, cache_read_price = 0 "
                       "WHERE model_id = 'zz-or'")  # as a previous run stored it
    before = (await _row(conn, "nous", "zz-or"))["updated_at"]
    await _refresh(conn, "nous", ["holder", "zz-or"], sources=sources)
    assert (await _row(conn, "nous", "zz-or"))["updated_at"] == before


@pytest.mark.asyncio
async def test_roles_prefer_provider_default_over_cheapest(conn):
    main = "Qwen/Qwen3-235B-A22B-Instruct-2507"  # NebiusProvider.MODEL_MAIN
    await _insert(conn, "nebius", main, inp=1, out=3, price_source="provider")
    await _insert(conn, "nebius", "tiny-1b", inp=0.01, out=0.02, price_source="provider")
    report = await _refresh(conn, "nebius", [main, "tiny-1b"])
    assert report.role_moves == {"narration": main, "mechanical": main}
    # Default model not enabled: the cheapest enabled one, as before.
    await conn.execute("UPDATE llm_models SET roles = '{}', status = 'pending', source = 'manual' "
                       "WHERE model_id = $1", main)
    report = await _refresh(conn, "nebius", [main, "tiny-1b"])
    assert report.role_moves == {"narration": "tiny-1b", "mechanical": "tiny-1b"}


@pytest.mark.asyncio
async def test_unpriced_enabled_row_never_takes_a_role(conn):
    await _holder(conn, "dead")
    await _insert(conn, "mistral", "noprice", rank=0)  # enabled, kept without a price
    await _insert(conn, "mistral", "priced", rank=5, inp=1, out=1, price_source="code")
    report = await _refresh(conn, "mistral", ["dead", "noprice", "priced"],
                            prober=_prober({"dead": "NotFoundError: Error code: 404"}))
    assert report.role_moves == {"narration": "priced", "mechanical": "priced"}
    assert (await _row(conn, "mistral", "noprice"))["roles"] == []


@pytest.mark.asyncio
async def test_unpriced_pending_rows_are_not_probed(conn):
    calls = []
    await _refresh(conn, "mistral", [PRICED, "zz-unpriced"], prober=_prober(calls=calls))
    assert [m for m, _ in calls] == ["zz-new"]
    row = await _row(conn, "mistral", "zz-unpriced")
    assert row["status"] == "pending" and row["last_probed_at"] is None


@pytest.mark.asyncio
async def test_failed_rows_reprobed_at_most_weekly(conn):
    await _holder(conn)
    for model_id, days in (("failed-recent", 2), ("failed-old", 8)):
        await _insert(conn, "mistral", model_id, status="failed", inp=1, out=1, price_source="code")
        await conn.execute(
            "UPDATE llm_models SET last_probed_at = now() - make_interval(days => $2) "
            "WHERE model_id = $1", model_id, days)
    listing = ["holder", "failed-recent", "failed-old"]
    calls = []
    await _refresh(conn, "mistral", listing, prober=_prober(calls=calls))
    assert sorted(m for m, _ in calls) == ["failed-old", "holder"]
    assert (await _row(conn, "mistral", "failed-recent"))["status"] == "failed"
    calls.clear()
    await _refresh(conn, "mistral", listing, prober=_prober(calls=calls), reprobe_all=True)
    assert "failed-recent" in [m for m, _ in calls]


@pytest.mark.asyncio
async def test_probes_run_outside_the_write_transaction(conn, test_pool):
    """No lock while paying for probes: a manual action during probing is neither
    blocked nor overwritten, and a crash mid-probing writes nothing."""
    await _holder(conn)
    await _insert(conn, "mistral", "backup", rank=2, inp=1, out=1, price_source="code")
    seen = []

    async def prober(provider_name, model, profile):
        seen.append(conn.is_in_transaction())
        if model == "holder":
            async with test_pool.acquire() as other:
                await other.execute("SET lock_timeout = '2s'")
                await other.execute(
                    "UPDATE llm_models SET status = 'retired', source = 'manual' "
                    "WHERE provider = 'mistral' AND model_id = 'backup'")
        return {name: ProbeResult(True, "ok") for name in ("stream", "json", "structured")}

    await _refresh(conn, "mistral", ["holder", "backup", PRICED], prober=prober)
    assert seen and not any(seen)
    backup = await _row(conn, "mistral", "backup")
    assert backup["status"] == "retired" and backup["source"] == "manual"
    assert (await _row(conn, "mistral", "zz-new"))["status"] == "enabled"

    async def crash(provider_name, model, profile):
        raise asyncio.CancelledError()  # e.g. the scheduled task is killed

    await _insert(conn, "mistral", "zz-other", status="pending", inp=1, out=1, price_source="code")
    with pytest.raises(asyncio.CancelledError):
        await _refresh(conn, "mistral", ["holder", "zz-other", PRICED], prober=crash)
    assert not conn.is_in_transaction()
    assert (await _row(conn, "mistral", "zz-other"))["last_probed_at"] is None


@pytest.mark.asyncio
async def test_price_payload_size_is_capped():
    import httpx

    def handler(request):
        return httpx.Response(200, content=b'{"a": "' + b"x" * 5000 + b'"}')

    transport = httpx.MockTransport(handler)
    with pytest.raises(ValueError, match="too large"):
        await refresh._http_get_json("https://example.test/x", transport=transport, max_bytes=1000)
    assert await refresh._http_get_json("https://example.test/x", transport=transport,
                                        max_bytes=10_000) == {"a": "x" * 5000}
