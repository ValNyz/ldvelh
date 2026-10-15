"""Live smoke test of every configured LLM provider and model.

Makes real (paid) API calls: a few hundred tokens per model. For each model it
runs the three call shapes the game uses:
  - stream:     narration-like streamed text
  - json:       JSON-in-text completion (mechanical step, resolver, Director)
  - structured: structured extraction in the provider's mode
                (tool_use / json_schema / text)

Keys come from config.Settings (environment, or backend/.env when run from
backend/), or with --user-email from the API keys that player saved in the
app (encrypted in the DB, decrypted with ENCRYPTION_KEY like /chat does).
Providers without a key are skipped. Keys are never printed.

Usage (from backend/):
  python -m scripts.smoke_providers                    # defaults of each provider
  python -m scripts.smoke_providers --all-models       # every listed chat model
  python -m scripts.smoke_providers --provider mistral --all-models --max-models 10
  python -m scripts.smoke_providers --provider anthropic --model claude-opus-5-5
  python -m scripts.smoke_providers --user-email me@example.com --all-models

Exit code 1 if any provider default model fails a probe.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field

from config import get_settings
from services.llm_providers import (
    LLMProvider,
    LLMUsage,
    StructuredOutputMode,
    _CLASSES,
    get_provider,
)
from services.pricing import lookup_pricing
from utils import parse_json_response

KEY_FIELDS = {
    "anthropic": "anthropic_api_key",
    "mistral": "mistral_api_key",
    "wandb": "wandb_api_key",
    "nebius": "nebius_api_key",
    "nous": "nous_api_key",
}

# Listed models that are not chat/text models.
NON_CHAT_MARKERS = (
    "embed", "moderation", "ocr", "tts", "whisper", "transcribe", "audio",
    "image", "vision-only", "rerank", "guard",
)

PROBE_TIMEOUT_S = 90

STREAM_SYSTEM = "Tu es le narrateur d'un jeu de rôle. Réponds en une seule phrase."
STREAM_USER = "Décris l'entrée d'une taverne."
JSON_SYSTEM = (
    "Réponds uniquement avec un objet JSON de la forme "
    '{"requires_test": true|false, "reason": "..."} sans aucun autre texte.'
)
JSON_USER = "Le joueur saute par-dessus un ruisseau large de deux mètres. Faut-il un jet de dés ?"
TOOL_NAME = "extract_characters"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "occupation": {"type": "string"}},
                "required": ["name", "occupation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["characters"],
    "additionalProperties": False,
}
EXTRACT_SYSTEM = "Extrais les personnages nommés du texte."
EXTRACT_USER = "Mira, la forgeronne, tend une épée à Ossek, le capitaine de la garde."


@dataclass
class ProbeResult:
    ok: bool
    detail: str = ""
    usage: LLMUsage | None = None


@dataclass
class ModelReport:
    provider: str
    model: str
    is_default: bool
    probes: dict[str, ProbeResult] = field(default_factory=dict)
    cost_usd: float = 0.0
    priced: bool = True

    @property
    def ok(self) -> bool:
        return all(p.ok for p in self.probes.values())


def is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in NON_CHAT_MARKERS)


def _short(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}"
    return text if len(text) <= 160 else text[:157] + "..."


async def probe_stream(provider: LLMProvider) -> ProbeResult:
    text, usage = "", None
    async for item in provider.stream(
        system_prompt=STREAM_SYSTEM,
        messages=[{"role": "user", "content": STREAM_USER}],
        temperature=0.7, max_tokens=300,
    ):
        if isinstance(item, LLMUsage):
            usage = item
        else:
            text += item
    if not text.strip():
        return ProbeResult(False, "empty stream", usage)
    return ProbeResult(True, f"{len(text)} chars", usage)


async def probe_json(provider: LLMProvider) -> ProbeResult:
    result = await provider.complete(
        system_prompt=JSON_SYSTEM,
        messages=[{"role": "user", "content": JSON_USER}],
        temperature=0.2, max_tokens=500,
    )
    parsed = parse_json_response(result.content)
    if not isinstance(parsed, dict) or "requires_test" not in parsed:
        return ProbeResult(False, f"unparseable: {result.content[:80]!r}", result.usage)
    return ProbeResult(True, f"requires_test={parsed['requires_test']}", result.usage)


async def probe_structured(provider: LLMProvider) -> ProbeResult:
    mode = provider.structured_output_mode
    messages = [{"role": "user", "content": EXTRACT_USER}]
    if mode == StructuredOutputMode.TOOL_USE:
        result = await provider.complete_with_tools(
            system_prompt=EXTRACT_SYSTEM, messages=messages,
            tools=[{"name": TOOL_NAME, "description": "Characters in the text",
                    "input_schema": TOOL_SCHEMA}],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            temperature=0.3, max_tokens=1000,
        )
        data, usage = result.tool_input, result.usage
    elif mode == StructuredOutputMode.JSON_SCHEMA:
        result = await provider.complete_with_schema(
            system_prompt=EXTRACT_SYSTEM, messages=messages,
            schema_name=TOOL_NAME, schema=TOOL_SCHEMA,
            temperature=0.3, max_tokens=1000,
        )
        data, usage = json.loads(result.content), result.usage
    else:
        result = await provider.complete(
            system_prompt=EXTRACT_SYSTEM + "\nRéponds uniquement en JSON : "
            + json.dumps(TOOL_SCHEMA, ensure_ascii=False),
            messages=messages, temperature=0.3, max_tokens=1000,
        )
        data, usage = parse_json_response(result.content), result.usage
    characters = data.get("characters") if isinstance(data, dict) else None
    if not isinstance(characters, list) or not characters:
        return ProbeResult(False, f"{mode.value}: no characters in {str(data)[:80]!r}", usage)
    return ProbeResult(True, f"{mode.value}: {len(characters)} characters", usage)


PROBES = {"stream": probe_stream, "json": probe_json, "structured": probe_structured}


async def run_probes(provider: LLMProvider) -> dict[str, ProbeResult]:
    """Run every probe on one provider instance; failures are reported, never raised."""
    results: dict[str, ProbeResult] = {}
    for name, probe in PROBES.items():
        try:
            results[name] = await asyncio.wait_for(probe(provider), timeout=PROBE_TIMEOUT_S)
        except Exception as e:  # report every failure, never stop the run
            results[name] = ProbeResult(False, _short(e))
    return results


async def run_model(provider_name: str, api_key: str, model: str, is_default: bool) -> ModelReport:
    report = ModelReport(provider_name, model, is_default)
    provider = get_provider(provider_name, api_key=api_key, model=model)
    pricing = lookup_pricing(model, provider_name)
    report.priced = bool(pricing.input or pricing.output)
    report.probes = await run_probes(provider)
    for result in report.probes.values():
        if result.usage:
            report.cost_usd += (
                result.usage.input_tokens * pricing.input
                + result.usage.output_tokens * pricing.output
            ) / 1_000_000
    return report


async def models_to_test(provider_name: str, api_key: str, args) -> list[tuple[str, bool]]:
    """(model_id, is_default) pairs: provider defaults first, then listed models if asked."""
    probe = get_provider(provider_name, api_key=api_key)
    defaults = [probe.MODEL_MAIN]
    mechanical = probe.model_name("mechanical")
    if mechanical not in defaults:
        defaults.append(mechanical)
    if args.model:
        return [(m, m in defaults) for m in args.model]
    chosen = [(m, True) for m in defaults]
    if args.all_models:
        listed = [m["id"] for m in await probe.list_models()]
        extra = [m for m in listed if m not in defaults and is_chat_model(m)]
        if args.max_models:
            extra = extra[: args.max_models]
        chosen += [(m, False) for m in extra]
    return chosen


def print_report(reports: list[ModelReport]) -> None:
    header = f"{'provider':<10} {'model':<48} {'stream':<7} {'json':<7} {'struct':<7} {'cost $':>9}  notes"
    print(header)
    print("-" * len(header))
    for r in reports:
        cells = [("OK" if r.probes[p].ok else "KO") for p in PROBES]
        notes = "; ".join(f"{p}: {r.probes[p].detail}" for p in PROBES if not r.probes[p].ok)
        if not r.priced:
            notes = (notes + "; " if notes else "") + "no price in pricing table"
        tag = "*" if r.is_default else " "
        print(f"{r.provider:<10} {tag}{r.model[:47]:<47} {cells[0]:<7} {cells[1]:<7} "
              f"{cells[2]:<7} {r.cost_usd:>9.5f}  {notes}")
    print("\n* = provider default (narration or mechanical)")


async def user_api_keys(email: str) -> dict[str, str]:
    """Decrypted API keys a player saved in the app, by provider name."""
    import asyncpg

    from utils.crypto import decrypt_value

    conn = await asyncpg.connect(get_settings().database_url)
    try:
        prefs = await conn.fetchval(
            "SELECT preferences FROM users WHERE LOWER(email) = LOWER($1)", email
        )
    finally:
        await conn.close()
    if prefs is None:
        raise SystemExit(f"No user with email {email!r}")
    if isinstance(prefs, str):
        prefs = json.loads(prefs)
    keys = {}
    for provider_name, encrypted in (prefs.get("api_keys") or {}).items():
        try:
            keys[provider_name] = decrypt_value(encrypted)
        except Exception as e:
            print(f"[warn] {provider_name}: stored key cannot be decrypted ({type(e).__name__})")
    return keys


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", action="append", choices=sorted(_CLASSES))
    parser.add_argument("--model", action="append", help="test only these model ids")
    parser.add_argument("--all-models", action="store_true", help="also test every listed chat model")
    parser.add_argument("--max-models", type=int, default=0, help="cap extra models per provider")
    parser.add_argument("--user-email", help="use the API keys this player saved in the app")
    args = parser.parse_args(argv)

    settings = get_settings()
    saved_keys = await user_api_keys(args.user_email) if args.user_email else {}
    reports: list[ModelReport] = []
    for provider_name in args.provider or sorted(_CLASSES):
        api_key = saved_keys.get(provider_name) or getattr(
            settings, KEY_FIELDS.get(provider_name, ""), "")
        if not api_key:
            print(f"[skip] {provider_name}: no API key configured")
            continue
        try:
            targets = await models_to_test(provider_name, api_key, args)
        except Exception as e:
            print(f"[error] {provider_name}: cannot list models ({_short(e)})")
            continue
        for model, is_default in targets:
            print(f"[run] {provider_name} / {model}", flush=True)
            reports.append(await run_model(provider_name, api_key, model, is_default))

    if not reports:
        print("No provider tested (no API key found).")
        return 1
    print()
    print_report(reports)
    total = sum(r.cost_usd for r in reports)
    print(f"Total estimated cost: ${total:.4f}")
    return 1 if any(r.is_default and not r.ok for r in reports) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
