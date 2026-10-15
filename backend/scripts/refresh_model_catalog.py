"""Refresh the llm_models catalog from the providers' live offer (daily scheduled task).

For each provider with an API key:
  1. list its live models (Anthropic: the built-in MODELS plus existing rows);
     a listing failure (or an empty listing) writes nothing for that provider;
  2. insert new chat models as `pending`;
  3. retire `auto` rows the provider no longer lists (never `manual` ones);
  4. probe new, pending, failed and role-holding models (all with --reprobe-all),
     retrying once with an adjusted profile on a temperature / tool_choice error;
  5. set the status: probes OK + known price -> enabled when the provider may
     auto-enable (Anthropic never does), else pending; probe failure -> failed.
     `manual` rows keep their status and profile;
  6. make sure `narration` and `mechanical` each have an enabled model;
  7. fill prices: manual > provider listing > code table > models.dev > OpenRouter (estimate).

Keys come from config.Settings, else from the API keys saved in the app by the
player given with --user-email or CATALOG_KEYS_USER_EMAIL. Keys are never printed.

Usage (from backend/):
  python -m scripts.refresh_model_catalog [--provider P]... [--user-email E] [--reprobe-all] [--dry-run]
  python -m scripts.refresh_model_catalog --enable P MODEL
  python -m scripts.refresh_model_catalog --disable P MODEL
  python -m scripts.refresh_model_catalog --set-role P MODEL ROLE

Exit code 1 when a provider could not be listed, when a role lost its last
enabled model, or when no provider has a key. Probing makes real (paid) calls:
a few hundred tokens per probed model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field, replace
from typing import Awaitable, Callable

from config import get_settings
from llm.profile import DEFAULT_PROFILE, ModelProfile
from repos.llm_models import invalidate_catalog_cache
from scripts.smoke_providers import (
    KEY_FIELDS,
    ProbeResult,
    _short,
    is_chat_model,
    run_probes,
    user_api_keys,
)
from services.llm_providers import _CLASSES, AnthropicProvider, get_provider
from services.pricing import ModelPricing, lookup_pricing

logger = logging.getLogger(__name__)

ROLES = ("narration", "mechanical")
MODELS_DEV_URL = "https://models.dev/api.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
PRICE_FETCH_TIMEOUT_S = 20.0
BIG_PRICE_CHANGE = 0.5  # relative change that deserves a log line

Prober = Callable[[str, str, ModelProfile | None], Awaitable[dict[str, ProbeResult]]]
Lister = Callable[[str], Awaitable[list[dict]]]


# =============================================================================
# External price sources
# =============================================================================

@dataclass(frozen=True)
class PriceSources:
    """Payloads of the public price sources, fetched once per run (None = unavailable)."""

    models_dev: dict | None
    openrouter: dict | None

    def from_models_dev(self, provider: str, model_id: str) -> ModelPricing | None:
        try:
            cost = self.models_dev[provider]["models"][model_id]["cost"]
            return _priced(ModelPricing(
                float(cost.get("input") or 0), float(cost.get("output") or 0),
                float(cost.get("cache_write") or 0), float(cost.get("cache_read") or 0),
            ))
        except (KeyError, TypeError, ValueError, AttributeError):
            return None

    def openrouter_allowed(self, provider: str) -> bool:
        """OpenRouter is only an estimate, for providers models.dev does not cover."""
        if self.models_dev is None:
            return provider == "nous"
        return provider not in self.models_dev

    def from_openrouter(self, model_id: str) -> ModelPricing | None:
        if not self.openrouter:
            return None
        by_id = {}
        for m in self.openrouter.get("data") or []:
            if isinstance(m, dict) and isinstance(m.get("id"), str):
                by_id.setdefault(m["id"].lower(), m)
        for candidate in (model_id.lower(), f"nousresearch/{model_id}".lower()):
            m = by_id.get(candidate)
            if m is None:
                continue
            p = m.get("pricing") or {}
            try:
                return _priced(ModelPricing(
                    float(p.get("prompt") or 0) * 1e6, float(p.get("completion") or 0) * 1e6,
                    float(p.get("input_cache_write") or 0) * 1e6,
                    float(p.get("input_cache_read") or 0) * 1e6,
                ))
            except (TypeError, ValueError, AttributeError):
                return None
        return None


def _priced(p: ModelPricing) -> ModelPricing | None:
    return p if (p.input > 0 or p.output > 0) else None


async def _http_get_json(url: str):
    import httpx

    async with httpx.AsyncClient(timeout=PRICE_FETCH_TIMEOUT_S) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def fetch_price_sources(fetch=None) -> PriceSources:
    """Fetch models.dev and OpenRouter once; a failure only disables that source."""
    fetch = fetch or _http_get_json
    payloads = {}
    checks = {
        "models.dev": (MODELS_DEV_URL, lambda d: isinstance(d, dict) and bool(d)),
        "openrouter": (OPENROUTER_URL, lambda d: isinstance(d, dict) and isinstance(d.get("data"), list)),
    }
    for name, (url, valid) in checks.items():
        try:
            data = await fetch(url)
            if not valid(data):
                raise ValueError("malformed payload")
            payloads[name] = data
        except Exception as e:
            logger.warning(f"[catalog] price source {name} unavailable: {_short(e)}")
            payloads[name] = None
    return PriceSources(models_dev=payloads["models.dev"], openrouter=payloads["openrouter"])


def resolve_price(provider: str, model_id: str, listed: dict | None,
                  sources: PriceSources) -> tuple[ModelPricing, str] | None:
    """First hit wins: provider listing, code table, models.dev, OpenRouter (estimate)."""
    listed = listed or {}
    try:
        from_listing = _priced(ModelPricing(
            float(listed.get("input_price") or 0), float(listed.get("output_price") or 0),
            float(listed.get("cache_write_price") or 0), float(listed.get("cache_read_price") or 0),
        ))
    except (TypeError, ValueError):
        from_listing = None
    if from_listing:
        return from_listing, "provider"
    code = _priced(lookup_pricing(model_id, provider))
    if code:
        return code, "code"
    md = sources.from_models_dev(provider, model_id)
    if md:
        return md, "models.dev"
    if sources.openrouter_allowed(provider):
        estimate = sources.from_openrouter(model_id)
        if estimate:
            logger.info(f"[catalog] {provider}/{model_id}: OpenRouter price used as an estimate")
            return estimate, "openrouter"
    return None


# =============================================================================
# Live listing / probing
# =============================================================================

def live_lister(provider_name: str, api_key: str) -> Lister:
    async def lister(name: str) -> list[dict]:
        if name == "anthropic":
            return [{"id": m, "label": label} for m, label in AnthropicProvider.MODELS.items()]
        # Providers swallow listing errors and return []: the caller treats [] as a failure.
        return await get_provider(name, api_key=api_key).list_models()
    return lister


def live_prober(api_key: str) -> Prober:
    async def prober(name: str, model: str, profile: ModelProfile | None):
        return await run_probes(get_provider(name, api_key=api_key, model=model, profile=profile))
    return prober


def _base_profile(provider: str, model_id: str, stored: dict | None) -> ModelProfile | None:
    """Row profile; empty -> provider fallback rules (R5). An unknown Claude id needs
    an explicit profile, else the Anthropic provider would swap it for its default model."""
    if stored:
        return ModelProfile.from_dict(stored)
    if provider == "anthropic" and model_id not in AnthropicProvider.MODELS:
        fallbacks = AnthropicProvider.FALLBACK_PROFILES
        return fallbacks.get(model_id, fallbacks[AnthropicProvider.MODEL_MAIN])
    return None


def _all_ok(results: dict[str, ProbeResult]) -> bool:
    return bool(results) and all(r.ok for r in results.values())


async def probe_with_retry(prober: Prober, provider: str, model_id: str,
                           profile: ModelProfile | None):
    """Probe; on a temperature / tool_choice rejection retry with that rule adjusted.

    Returns (results, profile used last, whether the profile was adjusted)."""
    results = await prober(provider, model_id, profile)
    adjusted = False
    for _ in range(2):
        if _all_ok(results):
            break
        errors = " ".join(r.detail.lower() for r in results.values() if not r.ok)
        current = profile or DEFAULT_PROFILE
        fixed = current
        if "temperature" in errors and current.send_temperature:
            fixed = replace(fixed, send_temperature=False)
        if "tool_choice" in errors and current.force_tool:
            fixed = replace(fixed, force_tool=False)
        if fixed == current:
            break
        profile, adjusted = fixed, True
        results = await prober(provider, model_id, profile)
    return results, profile, adjusted


# =============================================================================
# Refresh one provider
# =============================================================================

@dataclass
class RefreshReport:
    provider: str
    error: str | None = None
    inserted: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    probed: dict[str, bool] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)  # model -> new status
    role_moves: dict[str, str] = field(default_factory=dict)  # role -> model
    roles_lost: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.roles_lost


def _as_dict(value) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def _f(v) -> float | None:
    return float(v) if v is not None else None


_COLUMNS = ("label", "status", "roles", "input_price", "output_price", "cache_write_price",
            "cache_read_price", "price_source", "profile", "probe_results", "last_probed_at")


async def refresh_provider(conn, provider_name: str, api_key: str, *, auto_enable: bool,
                           reprobe_all: bool, prober: Prober,
                           price_sources: PriceSources | None = None,
                           lister: Lister | None = None, dry_run: bool = False) -> RefreshReport:
    report = RefreshReport(provider_name)
    sources = price_sources or PriceSources(None, None)
    lister = lister or live_lister(provider_name, api_key)

    # 1. Live listing: on failure, nothing is written for this provider.
    try:
        listing = await lister(provider_name)
    except Exception as e:
        listing, error = [], _short(e)
    else:
        error = None if listing else "empty model list"
    if error:
        report.error = f"cannot list models ({error})"
        logger.error(f"[catalog] {provider_name}: {report.error}; nothing changed")
        return report
    listed = {m["id"]: m for m in listing if isinstance(m, dict) and m.get("id")}

    tx = conn.transaction()
    await tx.start()
    try:
        await _refresh_rows(conn, provider_name, listed, report, auto_enable=auto_enable,
                            reprobe_all=reprobe_all, prober=prober, sources=sources)
    except BaseException:
        await tx.rollback()
        raise
    if dry_run:
        await tx.rollback()
    else:
        await tx.commit()
        invalidate_catalog_cache()  # this process only; others expire within 10 min
    return report


async def _refresh_rows(conn, provider: str, listed: dict[str, dict], report: RefreshReport, *,
                        auto_enable: bool, reprobe_all: bool, prober: Prober,
                        sources: PriceSources) -> None:
    rows = {r["model_id"]: dict(r) for r in await conn.fetch(
        "SELECT * FROM llm_models WHERE provider = $1 FOR UPDATE", provider)}
    for r in rows.values():
        r["profile"] = _as_dict(r["profile"])
        r["roles"] = list(r["roles"] or [])
    if provider == "anthropic":
        # No discovery endpoint: rows we already know are never retired.
        listed = {**{m: {"id": m} for m in rows}, **listed}
    had_enabled = {role: any(r["status"] == "enabled" and role in r["roles"] for r in rows.values())
                   for role in ROLES}
    dirty: set[str] = set()

    # 2. New chat models arrive as pending.
    new_ids = [m for m in listed if m not in rows and is_chat_model(m)]
    for model_id in new_ids:
        label = str(listed[model_id].get("label") or model_id)[:200]
        await conn.execute(
            "INSERT INTO llm_models (provider, model_id, label, status, source) "
            "VALUES ($1, $2, $3, 'pending', 'auto')", provider, model_id, label)
        rows[model_id] = {"model_id": model_id, "label": label, "status": "pending", "roles": [],
                          "default_rank": None, "input_price": None, "output_price": None,
                          "cache_write_price": None, "cache_read_price": None,
                          "price_source": None, "profile": {}, "probe_results": None,
                          "source": "auto", "last_probed_at": None}
    report.inserted = new_ids

    # 3. Auto rows the provider no longer lists are retired.
    for model_id, r in rows.items():
        if model_id not in listed and r["source"] == "auto" and r["status"] != "retired":
            r["status"] = "retired"
            dirty.add(model_id)
            report.retired.append(model_id)

    # 7 (before 5: the status needs the price). Prices, unless set by hand.
    for model_id, r in rows.items():
        if model_id not in listed or r["price_source"] == "manual":
            continue
        found = resolve_price(provider, model_id, listed.get(model_id), sources)
        if not found:
            continue
        price, source = found
        new = (price.input, price.output, price.cache_write, price.cache_read)
        old = tuple(_f(r[c]) for c in ("input_price", "output_price", "cache_write_price",
                                       "cache_read_price"))
        if old == new and r["price_source"] == source:
            continue
        for o, n in ((old[0], new[0]), (old[1], new[1])):
            if o and abs(n - o) / o > BIG_PRICE_CHANGE:
                logger.warning(f"[catalog] {provider}/{model_id}: price change "
                               f"{old[0]}/{old[1]} -> {new[0]}/{new[1]} ({source})")
                break
        r.update(input_price=new[0], output_price=new[1], cache_write_price=new[2],
                 cache_read_price=new[3], price_source=source)
        dirty.add(model_id)

    # 4-5. Probe and set the status.
    for model_id, r in rows.items():
        if model_id not in listed:
            continue
        needs_probe = (model_id in new_ids or r["status"] in ("pending", "failed", "retired")
                       or bool(r["roles"]) or reprobe_all)
        if not needs_probe:
            continue
        base = _base_profile(provider, model_id, r["profile"])
        results, used, adjusted = await probe_with_retry(prober, provider, model_id, base)
        ok = _all_ok(results)
        report.probed[model_id] = ok
        r["probe_results"] = {name: {"ok": p.ok, "detail": p.detail} for name, p in results.items()}
        r["last_probed_at"] = "now"
        dirty.add(model_id)
        if r["source"] == "manual":
            if adjusted and ok:
                logger.warning(f"[catalog] {provider}/{model_id}: manual row passes only with "
                               f"profile {used.to_dict()}; profile left unchanged")
            continue
        if ok and used is not None and (adjusted or not r["profile"]):
            # R5: save the profile the model needed (or the Claude rules an unknown id needs).
            r["profile"] = used.to_dict()
        priced = r["input_price"] is not None or r["output_price"] is not None
        if not ok:
            status = "failed"
        elif priced and (auto_enable or r["status"] == "enabled"):
            status = "enabled"
        elif r["status"] == "enabled":
            status = "enabled"  # never drop a working model for a missing price
            logger.warning(f"[catalog] {provider}/{model_id}: enabled without a known price")
        else:
            status = "pending"
        if status != r["status"]:
            report.statuses[model_id] = status
        r["status"] = status

    # 6. Each role keeps an enabled holder, else moves to the preferred enabled model.
    enabled = [r for r in rows.values() if r["status"] == "enabled"]
    for role in ROLES:
        if any(role in r["roles"] for r in enabled):
            continue
        ranked = sorted((r for r in enabled if r["default_rank"] is not None),
                        key=lambda r: (r["default_rank"], r["model_id"]))
        cheapest = sorted(enabled, key=lambda r: (r["output_price"] is None,
                                                  _f(r["output_price"]) or 0.0, r["model_id"]))
        chosen = (ranked or cheapest or [None])[0]
        if chosen is None:
            if had_enabled[role]:
                report.roles_lost.append(role)
                logger.error(f"[catalog] {provider}: no enabled model left for {role}")
            continue
        for r in rows.values():
            if role in r["roles"]:
                r["roles"].remove(role)
                dirty.add(r["model_id"])
        chosen["roles"].append(role)
        dirty.add(chosen["model_id"])
        report.role_moves[role] = chosen["model_id"]
        logger.warning(f"[catalog] {provider}: {role} moved to {chosen['model_id']}")

    for model_id in dirty:
        r = rows[model_id]
        probed_now = r["last_probed_at"] == "now"
        await conn.execute(
            """UPDATE llm_models SET status = $3, roles = $4, input_price = $5, output_price = $6,
                   cache_write_price = $7, cache_read_price = $8, price_source = $9,
                   profile = $10, probe_results = $11,
                   last_probed_at = CASE WHEN $12 THEN now() ELSE last_probed_at END,
                   updated_at = now()
               WHERE provider = $1 AND model_id = $2""",
            provider, model_id, r["status"], r["roles"], r["input_price"], r["output_price"],
            r["cache_write_price"], r["cache_read_price"], r["price_source"], r["profile"],
            _as_dict(r["probe_results"]) or None, probed_now,
        )


# =============================================================================
# Manual actions
# =============================================================================

async def manual_action(conn, action: str, provider: str, model_id: str, role: str | None = None) -> str | None:
    """Apply --enable / --disable / --set-role; returns an error message or None."""
    if provider not in _CLASSES:
        return f"unknown provider {provider!r}"
    exists = await conn.fetchval(
        "SELECT 1 FROM llm_models WHERE provider = $1 AND model_id = $2", provider, model_id)
    if action == "enable":
        if not exists:
            # Lets an operator add a model the provider listing cannot show (Anthropic).
            profile = _base_profile(provider, model_id, None)
            await conn.execute(
                "INSERT INTO llm_models (provider, model_id, label, status, profile, source) "
                "VALUES ($1, $2, $2, 'enabled', $3, 'manual')",
                provider, model_id, profile.to_dict() if profile else {})
        else:
            await conn.execute(
                "UPDATE llm_models SET status = 'enabled', source = 'manual', updated_at = now() "
                "WHERE provider = $1 AND model_id = $2", provider, model_id)
        return None
    if not exists:
        return f"no catalog row for {provider}/{model_id}"
    if action == "disable":
        await conn.execute(
            "UPDATE llm_models SET status = 'retired', source = 'manual', updated_at = now() "
            "WHERE provider = $1 AND model_id = $2", provider, model_id)
        return None
    if role not in ROLES:
        return f"unknown role {role!r} (expected one of {', '.join(ROLES)})"
    async with conn.transaction():
        await conn.execute(
            "UPDATE llm_models SET roles = array_remove(roles, $2), updated_at = now() "
            "WHERE provider = $1 AND $2 = ANY(roles)", provider, role)
        await conn.execute(
            "UPDATE llm_models SET roles = array_append(roles, $3), source = 'manual', "
            "updated_at = now() WHERE provider = $1 AND model_id = $2", provider, model_id, role)
    return None


# =============================================================================
# CLI
# =============================================================================

async def _connect(url: str):
    import asyncpg

    conn = await asyncpg.connect(url)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    return conn


async def _close(conn) -> None:
    await conn.close()


async def resolve_keys(settings, providers: list[str], user_email: str | None) -> dict[str, str]:
    """Server keys first, else the keys a player saved in the app. Never printed."""
    keys = {p: getattr(settings, KEY_FIELDS.get(p, ""), "") for p in providers}
    email = user_email or settings.catalog_keys_user_email
    if email and not all(keys.values()):
        try:
            saved = await user_api_keys(email)
        except SystemExit as e:  # unknown user
            print(f"[catalog] {e}")
            saved = {}
        for p in providers:
            keys[p] = keys[p] or saved.get(p, "")
    return {p: k for p, k in keys.items() if k}


def _print_report(r: RefreshReport) -> None:
    if r.error:
        print(f"[catalog] {r.provider}: ERROR {r.error}")
        return
    probed_ok = sum(r.probed.values())
    print(f"[catalog] {r.provider}: {len(r.inserted)} new, {len(r.retired)} retired, "
          f"{probed_ok}/{len(r.probed)} probed OK")
    for model, status in sorted(r.statuses.items()):
        print(f"           {model} -> {status}")
    for role, model in r.role_moves.items():
        print(f"           {role} -> {model}")
    for role in r.roles_lost:
        print(f"           {role}: NO ENABLED MODEL")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", action="append", choices=sorted(_CLASSES))
    parser.add_argument("--user-email", help="use the API keys this player saved in the app")
    parser.add_argument("--reprobe-all", action="store_true", help="probe every listed model")
    parser.add_argument("--dry-run", action="store_true", help="probe and report, write nothing")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--enable", nargs=2, metavar=("PROVIDER", "MODEL"))
    actions.add_argument("--disable", nargs=2, metavar=("PROVIDER", "MODEL"))
    actions.add_argument("--set-role", nargs=3, metavar=("PROVIDER", "MODEL", "ROLE"))
    args = parser.parse_args(argv)
    settings = get_settings()

    for action in ("enable", "disable", "set_role"):
        values = getattr(args, action)
        if values:
            conn = await _connect(settings.database_url)
            try:
                error = await manual_action(conn, action.replace("set_role", "set-role"), *values)
            finally:
                await _close(conn)
            if error:
                print(f"[catalog] {error}")
                return 1
            invalidate_catalog_cache()
            print(f"[catalog] {action.replace('_', '-')} {' '.join(values)}: done")
            return 0

    providers = args.provider or sorted(_CLASSES)
    keys = await resolve_keys(settings, providers, args.user_email)
    if not keys:
        print("[catalog] no API key for any provider; nothing written")
        return 1
    auto = {p.strip() for p in settings.catalog_auto_enable.split(",") if p.strip()}
    auto.discard("anthropic")  # Anthropic discoveries always wait for an operator

    sources = await fetch_price_sources()
    conn = await _connect(settings.database_url)
    reports = []
    try:
        for name in providers:
            if name not in keys:
                print(f"[catalog] {name}: no API key, skipped")
                continue
            reports.append(await refresh_provider(
                conn, name, keys[name], auto_enable=name in auto, reprobe_all=args.reprobe_all,
                prober=live_prober(keys[name]), price_sources=sources,
                lister=live_lister(name, keys[name]), dry_run=args.dry_run,
            ))
            _print_report(reports[-1])
    finally:
        await _close(conn)
    if args.dry_run:
        print("[catalog] dry run: nothing written")
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(asyncio.run(main()))
