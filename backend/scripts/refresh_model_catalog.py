"""Refresh the llm_models catalog from the providers' live offer (daily scheduled task).

For each provider with an API key:
  1. list its live models (Anthropic: the built-in MODELS plus existing rows);
     a listing failure (or an empty listing) writes nothing for that provider;
  2. insert new chat models as `pending`;
  3. retire `auto` rows the provider no longer lists (never `manual` ones);
     enabled rows and role holders only after 3 consecutive absent runs;
  4. probe role holders and new / pending / failed rows that have a price (an
     unpriced row can never be enabled), failed rows at most weekly; all listed
     models with --reprobe-all. Retry once with an adjusted profile on a
     temperature / tool_choice error. Probes run BEFORE the per-provider write
     transaction: a run killed while probing writes nothing and holds no lock;
  5. set the status: probes OK + known price -> enabled when the provider may
     auto-enable (Anthropic never does) or was enabled before, else pending;
     probe failure -> failed, except an enabled row, demoted only after 3
     consecutive failed runs or at once on a permanent error (404, unknown
     model). `manual` rows keep their status and profile (retired ones are not probed);
  6. make sure `narration` and `mechanical` each have an enabled, priced model
     (seeded rank, then the provider's default for that role, then the cheapest);
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
import math
import sys
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field, replace
from typing import Awaitable, Callable

from config import get_settings
from llm.profile import DEFAULT_PROFILE, ModelProfile
from repos.llm_models import CORE_ROLES, OPTIONAL_ROLES, invalidate_catalog_cache
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

ROLES = CORE_ROLES
# --set-role also accepts the optional roles, which the refresh never moves.
SETTABLE_ROLES = CORE_ROLES + OPTIONAL_ROLES
MODELS_DEV_URL = "https://models.dev/api.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
PRICE_FETCH_TIMEOUT_S = 20.0
MAX_PAYLOAD_BYTES = 20 * 1024 * 1024  # price source payloads above this are refused
MAX_PRICE = 1e5  # USD per million tokens; also keeps values inside numeric(12, 6)
FAILED_REPROBE_AFTER = timedelta(days=7)  # failed rows are re-probed at most weekly
BIG_PRICE_CHANGE = 0.5  # relative change that deserves a log line
# An enabled model survives this many consecutive bad runs (failed probes, or
# absence from a non-empty listing) before it is demoted: 429 / 5xx / timeouts
# and listing glitches are usually transient.
DEMOTE_AFTER_RUNS = 3
# Probe errors that mean the model is gone for good: demote at once.
PERMANENT_ERROR_MARKERS = (
    "error code: 404", "status 404", "status code 404", "notfounderror", "model_not_found", "not_found_error", "model not found",
    "does not exist", "invalid model", "unknown model", "invalid_model",
)

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
        if self.models_dev is None:
            return None
        try:
            cost = self.models_dev[provider]["models"][model_id]["cost"]
            return _priced(ModelPricing(
                float(cost.get("input") or 0), float(cost.get("output") or 0),
                float(cost.get("cache_write") or 0), float(cost.get("cache_read") or 0),
            ), f"models.dev {provider}/{model_id}")
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
                ), f"openrouter {model_id}")
            except (TypeError, ValueError, AttributeError):
                return None
        return None


def _priced(p: ModelPricing, origin: str = "price") -> ModelPricing | None:
    """The price rounded to the DB precision, None when unknown (zero) or not sane.

    External values can be NaN / Infinity / negative / absurd: NaN would make
    /api/providers fail to serialize, too large a value overflows numeric(12, 6)."""
    values = (p.input, p.output, p.cache_write, p.cache_read)
    if not all(math.isfinite(v) and 0 <= v < MAX_PRICE for v in values):
        logger.warning(f"[catalog] ignoring invalid price from {origin}: {values}")
        return None
    # Rounded like numeric(12, 6), so an unchanged price compares equal to the stored one.
    p = ModelPricing(*(round(v, 6) for v in values))
    return p if (p.input > 0 or p.output > 0) else None


async def _http_get_json(url: str, *, transport=None, max_bytes: int = MAX_PAYLOAD_BYTES):
    """GET a JSON payload, refusing bodies above max_bytes (read in chunks)."""
    import httpx

    async with httpx.AsyncClient(timeout=PRICE_FETCH_TIMEOUT_S, transport=transport) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ValueError(f"payload too large (> {max_bytes} bytes)")
    return json.loads(bytes(body))


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
        ), f"{provider} listing {model_id}")
    except (TypeError, ValueError):
        from_listing = None
    if from_listing:
        return from_listing, "provider"
    code = _priced(lookup_pricing(model_id, provider), f"code table {model_id}")
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


def _fallback_profile(provider: str, model_id: str) -> ModelProfile:
    """The rules the provider applies to this model when the catalog gives none."""
    if provider == "anthropic":
        fallbacks = AnthropicProvider.FALLBACK_PROFILES
        return fallbacks.get(model_id, fallbacks[AnthropicProvider.MODEL_MAIN])
    return DEFAULT_PROFILE


def _base_profile(provider: str, model_id: str, stored: dict | None) -> ModelProfile | None:
    """Row profile; empty -> provider fallback rules (R5). An unknown Claude id needs
    an explicit profile, else the Anthropic provider would swap it for its default model."""
    if stored:
        return ModelProfile.from_dict(stored)
    if provider == "anthropic" and model_id not in AnthropicProvider.MODELS:
        return _fallback_profile(provider, model_id)
    return None


def _all_ok(results: dict[str, ProbeResult]) -> bool:
    return bool(results) and all(r.ok for r in results.values())


def _is_permanent(results: dict[str, ProbeResult]) -> bool:
    errors = " ".join(r.detail.lower() for r in results.values() if not r.ok)
    return any(marker in errors for marker in PERMANENT_ERROR_MARKERS)


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
        current = profile or _fallback_profile(provider, model_id)
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
    # Optional roles (identity...) left without an enabled, priced holder: never moved,
    # the narration model serves them until an operator sets a holder (--set-role).
    optional_roles_lost: list[str] = field(default_factory=list)

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


def _priced_row(r: dict) -> bool:
    return r["input_price"] is not None or r["output_price"] is not None


async def _read_rows(conn, provider: str, *, lock: bool) -> dict[str, dict]:
    query = "SELECT * FROM llm_models WHERE provider = $1" + (" FOR UPDATE" if lock else "")
    rows = {r["model_id"]: dict(r) for r in await conn.fetch(query, provider)}
    for r in rows.values():
        r["profile"] = _as_dict(r["profile"])
        r["roles"] = list(r["roles"] or [])
        r["probe_results"] = _as_dict(r["probe_results"])
    return rows


def _new_row(model_id: str, label: str) -> dict:
    return {"model_id": model_id, "label": label, "status": "pending", "roles": [],
            "default_rank": None, "input_price": None, "output_price": None,
            "cache_write_price": None, "cache_read_price": None,
            "price_source": None, "profile": {}, "probe_results": {},
            "source": "auto", "last_probed_at": None}


def _with_known_rows(provider: str, listed: dict[str, dict], rows: dict[str, dict]) -> dict[str, dict]:
    if provider == "anthropic":
        # No discovery endpoint: rows we already know are never retired.
        return {**{m: {"id": m} for m in rows}, **listed}
    return listed


def _needs_probe(r: dict, *, priced: bool, reprobe_all: bool, now: datetime) -> bool:
    """Whether this run pays for probing the row (rows already locked out by hand never)."""
    if r["source"] == "manual" and r["status"] == "retired":
        return False  # switched off by hand: no paid probe
    if reprobe_all or r["roles"]:
        return True
    if r["status"] == "enabled":
        return False
    was_enabled = bool(r["probe_results"].get("was_enabled"))
    if not priced and not was_enabled:
        return False  # can never be enabled without a price: probing would be wasted
    last = r["last_probed_at"]
    if r["status"] == "failed" and not was_enabled and last is not None \
            and now - last < FAILED_REPROBE_AFTER:
        return False  # failed rows are re-probed at most weekly
    return True


@dataclass
class _Plan:
    """Decisions taken before the write transaction (no lock held while probing)."""

    listed: dict[str, dict]
    prices: dict[str, tuple[ModelPricing, str]]  # model -> resolved price (not manual rows)
    to_probe: dict[str, ModelProfile | None]  # model -> base profile


def _plan(provider: str, listed: dict[str, dict], rows: dict[str, dict], *,
          reprobe_all: bool, sources: PriceSources) -> _Plan:
    listed = _with_known_rows(provider, listed, rows)
    now = datetime.now(timezone.utc)
    prices: dict[str, tuple[ModelPricing, str]] = {}
    to_probe: dict[str, ModelProfile | None] = {}
    for model_id in listed:
        r = rows.get(model_id)
        if r is None:
            if not is_chat_model(model_id):
                continue
            r = _new_row(model_id, model_id)
        if r["price_source"] != "manual":
            found = resolve_price(provider, model_id, listed.get(model_id), sources)
            if found:
                prices[model_id] = found
        priced = model_id in prices or _priced_row(r)
        if _needs_probe(r, priced=priced, reprobe_all=reprobe_all, now=now):
            to_probe[model_id] = _base_profile(provider, model_id, r["profile"])
    return _Plan(listed, prices, to_probe)


async def refresh_provider(conn, provider_name: str, api_key: str, *, auto_enable: bool,
                           reprobe_all: bool, prober: Prober,
                           price_sources: PriceSources | None = None,
                           lister: Lister | None = None, dry_run: bool = False) -> RefreshReport:
    """List, plan and probe without any lock, then apply in one short transaction.

    The paid probes run before the transaction: a run killed while probing
    (scheduled task timeout) writes nothing for this provider instead of holding
    `FOR UPDATE` locks, and manual actions are never blocked by a refresh."""
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

    # Decide what to probe from an unlocked read, then pay for the probes.
    plan = _plan(provider_name, listed, await _read_rows(conn, provider_name, lock=False),
                 reprobe_all=reprobe_all, sources=sources)
    outcomes = {}
    for model_id, base in plan.to_probe.items():
        outcomes[model_id] = await probe_with_retry(prober, provider_name, model_id, base)
        report.probed[model_id] = _all_ok(outcomes[model_id][0])

    tx = conn.transaction()
    await tx.start()
    try:
        await _apply(conn, provider_name, listed, plan, outcomes, report, auto_enable=auto_enable)
    except BaseException:
        await tx.rollback()
        raise
    if dry_run:
        await tx.rollback()
    else:
        await tx.commit()
        invalidate_catalog_cache()  # this process only; others expire within 10 min
    return report


async def _apply(conn, provider: str, listed: dict[str, dict], plan: _Plan, outcomes: dict,  # noqa: C901 - P6, frozen complexity debt: split _apply
                 report: RefreshReport, *, auto_enable: bool) -> None:
    """Re-read the rows under lock (an operator may have acted meanwhile) and apply the run."""
    rows = await _read_rows(conn, provider, lock=True)
    listed = _with_known_rows(provider, listed, rows)
    had_enabled = {role: any(r["status"] == "enabled" and role in r["roles"] for r in rows.values())
                   for role in (*ROLES, *OPTIONAL_ROLES)}
    dirty: set[str] = set()

    # 2. New chat models arrive as pending.
    new_ids = [m for m in listed if m not in rows and is_chat_model(m)]
    for model_id in new_ids:
        label = str(listed[model_id].get("label") or model_id)[:200]
        await conn.execute(
            "INSERT INTO llm_models (provider, model_id, label, status, source) "
            "VALUES ($1, $2, $3, 'pending', 'auto')", provider, model_id, label)
        rows[model_id] = _new_row(model_id, label)
    report.inserted = new_ids

    # 3. Auto rows the provider no longer lists are retired; enabled rows and
    # role holders only after DEMOTE_AFTER_RUNS consecutive absent runs.
    for model_id, r in rows.items():
        if model_id in listed:
            if r["probe_results"].get("absent"):
                r["probe_results"]["absent"] = 0
                dirty.add(model_id)
            continue
        if r["source"] != "auto" or r["status"] == "retired":
            continue
        dirty.add(model_id)
        if r["status"] == "enabled" or r["roles"]:
            absent = int(r["probe_results"].get("absent") or 0) + 1
            r["probe_results"]["absent"] = absent
            if absent < DEMOTE_AFTER_RUNS:
                logger.warning(f"[catalog] {provider}/{model_id}: missing from the listing "
                               f"({absent}/{DEMOTE_AFTER_RUNS}), kept")
                continue
        r["status"] = "retired"
        report.retired.append(model_id)

    # 7 (before 5: the status needs the price). Prices, unless set by hand.
    for model_id, r in rows.items():
        if model_id not in listed or r["price_source"] == "manual":
            continue
        found = plan.prices.get(model_id)
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

    # 4-5. Record the probes made before the transaction and set the status.
    for model_id, r in rows.items():
        if model_id not in listed or model_id not in outcomes:
            continue
        if r["source"] == "manual" and r["status"] == "retired":
            continue  # switched off by hand while probing
        results, used, adjusted = outcomes[model_id]
        ok = _all_ok(results)
        previous = r["probe_results"]
        failures = 0 if ok else int(previous.get("failures") or 0) + 1
        r["probe_results"] = {name: {"ok": p.ok, "detail": p.detail} for name, p in results.items()}
        r["probe_results"].update(failures=failures, absent=int(previous.get("absent") or 0))
        if previous.get("was_enabled") and not ok:
            r["probe_results"]["was_enabled"] = True
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
        priced = _priced_row(r)
        was_enabled = r["status"] == "enabled" or bool(previous.get("was_enabled"))
        if not ok and r["status"] == "enabled" and not _is_permanent(results) \
                and failures < DEMOTE_AFTER_RUNS:
            status = "enabled"  # transient until proven otherwise
            logger.warning(f"[catalog] {provider}/{model_id}: probes failed "
                           f"({failures}/{DEMOTE_AFTER_RUNS}), kept enabled")
        elif not ok:
            status = "failed"
            if r["status"] == "enabled":
                r["probe_results"]["was_enabled"] = True
        elif priced and (auto_enable or was_enabled):
            status = "enabled"
        elif was_enabled:
            status = "enabled"  # never drop a working model for a missing price
            logger.warning(f"[catalog] {provider}/{model_id}: enabled without a known price")
        else:
            status = "pending"
        if status != r["status"]:
            report.statuses[model_id] = status
        r["status"] = status

    # 6. Each role keeps an enabled, priced holder, else moves to the preferred one:
    # seeded rank, then the provider's own default for that role, then the cheapest.
    # An unpriced model is hidden from players, so it never becomes a default.
    cls = _CLASSES.get(provider)
    provider_default = {
        "narration": getattr(cls, "MODEL_MAIN", None),
        "mechanical": getattr(cls, "MODEL_MECHANICAL", None) or getattr(cls, "MODEL_MAIN", None),
    }
    enabled = [r for r in rows.values() if r["status"] == "enabled" and _priced_row(r)]
    for role in ROLES:
        if any(role in r["roles"] for r in enabled):
            continue
        ranked = sorted((r for r in enabled if r["default_rank"] is not None),
                        key=lambda r: (r["default_rank"], r["model_id"]))
        preferred = [r for r in enabled if r["model_id"] == provider_default[role]]
        cheapest = sorted(enabled, key=lambda r: (r["output_price"] is None,
                                                  _f(r["output_price"]) or 0.0, r["model_id"]))
        chosen = (ranked or preferred or cheapest or [None])[0]
        if chosen is None:
            if had_enabled[role]:
                report.roles_lost.append(role)
                logger.error(f"[catalog] {provider}: no enabled, priced model left for {role}")
            continue
        for r in rows.values():
            if role in r["roles"]:
                r["roles"].remove(role)
                dirty.add(r["model_id"])
        chosen["roles"].append(role)
        dirty.add(chosen["model_id"])
        report.role_moves[role] = chosen["model_id"]
        logger.warning(f"[catalog] {provider}: {role} moved to {chosen['model_id']}")

    report.optional_roles_lost = _optional_roles_lost(provider, rows, had_enabled)

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
            r["probe_results"] or None, probed_now,
        )


def _optional_roles_lost(provider: str, rows: dict[str, dict],
                         had_enabled: dict[str, bool]) -> list[str]:
    """The optional roles that had an enabled holder before the run and have no enabled,
    priced one after it. Never moved (an operator chooses them); reported, since the
    identity resolver then runs on the narration model (several times the cost)."""
    lost = [
        role for role in OPTIONAL_ROLES
        if had_enabled[role] and not any(
            r["status"] == "enabled" and _priced_row(r) and role in r["roles"]
            for r in rows.values())
    ]
    for role in lost:
        logger.warning(f"[catalog] {provider}: no enabled, priced model left for {role}, "
                       "the narration model serves it")
    return lost


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
    if role not in SETTABLE_ROLES:
        return f"unknown role {role!r} (expected one of {', '.join(SETTABLE_ROLES)})"
    async with conn.transaction():
        await conn.execute(
            "UPDATE llm_models SET roles = array_remove(roles, $2), updated_at = now() "
            "WHERE provider = $1 AND $2 = ANY(roles)", provider, role)
        await conn.execute(
            "UPDATE llm_models SET roles = array_append(roles, $3), updated_at = now() "
            "WHERE provider = $1 AND model_id = $2", provider, model_id, role)
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
    for role in r.optional_roles_lost:
        print(f"           {role}: NO ENABLED MODEL (optional: the narration model serves it)")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
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
            try:
                report = await refresh_provider(
                    conn, name, keys[name], auto_enable=name in auto,
                    reprobe_all=args.reprobe_all, prober=live_prober(keys[name]),
                    price_sources=sources, lister=live_lister(name, keys[name]),
                    dry_run=args.dry_run,
                )
            except Exception as e:  # rolled back by refresh_provider; go on with the others
                logger.exception(f"[catalog] {name}: refresh crashed")
                report = RefreshReport(name, error=f"refresh crashed ({_short(e)})")
            reports.append(report)
            _print_report(reports[-1])
    finally:
        await _close(conn)
    if args.dry_run:
        print("[catalog] dry run: nothing written")
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(asyncio.run(main()))
