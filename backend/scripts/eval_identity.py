"""Evaluate a resolver on the identity gold corpus and write the report (#151, #154).

Two adapters: `legacy` (services/extraction/resolver.py, one call per scene) and `v2` (the
resolver v2, services/identity/resolution.py, on a scratch game of the database of
TEST_DATABASE_URL; `--tier cheap` turns its escalation off). Three ways to get the model
answers:

- live (default): real calls through the provider (`--provider`); the key comes from
  the server settings (ANTHROPIC_API_KEY...) or from the keys the player of
  CATALOG_KEYS_USER_EMAIL saved in the app;
- `--emit-prompts DIR`: no call; writes the requests exactly as the app would send them
  (model, options, system, messages[, tool]);
- `--import-responses DIR --responder KIND:DETAIL`: reads the raw model outputs answered
  to those requests elsewhere (by the responder, e.g. `subagent:claude-sonnet`), parses
  them with the app's code and scores them.

Legacy: one request per scene, `<scene id>.json`, answered in `<scene id>.txt`.

v2, staged (its calls depend on the previous answers): one request per model call,
`<token>.<n>.json` with its `purpose` and `model`, answered in `<token>.<n>.txt` (the
token hides the scene id, which names a gold category; `calls.request_token`)
(evals/identity/RESPONDERS.md). Both flags replay the answered calls in order and write
the first unanswered call of each scene as a new request; such a scene is pending.
`<DIR>/pending.json` lists the pending requests (file, purpose, model) and their count
per purpose is printed. `--emit-prompts` stops there; `--import-responses` scores only
when no scene is pending, else exits with PENDING_EXIT. With `--runs N` each run has its
own directory, `DIR/run1` ... `DIR/runN`. The replayed usage is estimated from the text
(evals/identity/calls.py) and the report says so.

The report goes to `<out>/<date>-<split>-<provider>-<models>[-<responder kind>].md|json`:
`<models>` names the app models the requests were built for, the responder kind marks
answers that did not come from the API. `--milestone pr2` adds the PR 2 gate of the
plan (hard pool, W, L, escalation rate and cost per turn). With `--gate` the exit code
is 1 when the gate fails: the milestone's with `--milestone`, else a measured row of the
spec's gate.

Usage (from backend/, or through scripts/eval-identity.sh from the repo root):
  python -m scripts.eval_identity --adapter legacy --split test --runs 1 --provider anthropic
  python -m scripts.eval_identity --adapter legacy --split dev --sequences --emit-prompts DIR
  python -m scripts.eval_identity --adapter legacy --split dev --sequences \
      --import-responses DIR --responder subagent:claude-sonnet
  python -m scripts.eval_identity --adapter v2 --split dev --emit-prompts DIR
  python -m scripts.eval_identity --adapter v2 --split dev --import-responses DIR \
      --responder subagent:claude-haiku+claude-sonnet --milestone pr2
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from evals.identity import runner
from evals.identity.adapters.legacy_resolver import (
    LegacyResolverAdapter,
    build_request,
    reference,
    replay_session,
)
from evals.identity.adapters.resolver_v2 import TIERS, ResolverV2Adapter
from evals.identity.calls import (
    Responses,
    Tap,
    dumps_request,
    holds_purpose,
    tapped_session,
    write_pending_index,
)
from evals.identity.corpus import Category
from evals.identity.leaks import leak_count
from evals.identity.report import MILESTONES
from llm.session import LLMSession, Purpose
from llm.usage import is_unpriced
from services.llm_providers import LLMProvider, get_provider, get_provider_catalog

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND / "tests" / "fixtures" / "identity"
OUT = BACKEND / "tests" / "reports" / "identity"
ADAPTERS = {"legacy": LegacyResolverAdapter, "v2": ResolverV2Adapter}
# The models each adapter takes in --models (role=model).
ROLES = {
    "legacy": ("resolver",),
    "v2": (Purpose.IDENTITY.value, Purpose.IDENTITY_STRONG.value),
}
OFFLINE_KEY = "offline"  # builds a provider client that never sends a request
PROVIDERS = sorted(get_provider_catalog()["providers"])
PENDING_EXIT = 3  # --import-responses with requests still to answer: nothing scored
SUBAGENT = "subagent"
SUBAGENT_NOTE = "subagent responders, to confirm with 3 API runs when a key exists"
CHEAP_NOTE = "Cheap tier: the small model's answers replayed, without the escalation."
CHEAP_REPLAY_NOTE = (
    "Cheap tier: the small model's answers of the cascade's responses replayed "
    "(the same stage-1 samples), without the escalation."
)


def import_note(responder: str) -> str:
    note = (
        f"Source: answers of {responder} to the emitted requests (not the API path: "
        "no thinking budget, no temperature, model tier of the responder)."
    )
    if responder.split(":", 1)[0] == SUBAGENT:
        note += f" {SUBAGENT_NOTE[0].upper()}{SUBAGENT_NOTE[1:]}."
    return note


def _parse_models(text: str | None, adapter: str) -> dict[str, str]:
    if not text:
        return {}
    pairs = [item.split("=", 1) for item in text.split(",")]
    if any(len(p) != 2 or not all(p) for p in pairs):
        raise SystemExit(f"--models: expected role=model[,role=model], got {text!r}")
    unknown = sorted({role for role, _ in pairs} - set(ROLES[adapter]))
    if unknown:
        raise SystemExit(
            f"--models: {', '.join(unknown)} is not a role of --adapter {adapter} "
            f"({', '.join(ROLES[adapter])})"
        )
    return dict(pairs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--adapter", choices=sorted(ADAPTERS), default="legacy")
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--provider", choices=PROVIDERS, default="anthropic")
    parser.add_argument(
        "--models",
        help="role=MODEL[,role=MODEL] (legacy: resolver; v2: identity, identity_strong; "
        "default: the app's choice)",
    )
    parser.add_argument(
        "--tier", choices=TIERS, default="cascade", help="v2: cheap = no escalation"
    )
    parser.add_argument("--milestone", choices=sorted(MILESTONES))
    parser.add_argument("--category", choices=Category.__args__)
    parser.add_argument("--scene", help="one scene id")
    parser.add_argument("--sequences", action="store_true", help="add the sequences")
    parser.add_argument("--gate", action="store_true", help="exit 1 if the gate fails")
    parser.add_argument("--root", type=Path, default=ROOT, help="corpus directory")
    parser.add_argument("--out", type=Path, default=OUT, help="report directory")
    parser.add_argument("--iterations", type=int, default=2000, help="bootstrap draws")
    parser.add_argument(
        "--needs-db",
        action="store_true",
        help="only print 1 if the adapter reads the database, else 0 (eval-identity.sh)",
    )
    io = parser.add_mutually_exclusive_group()
    io.add_argument("--emit-prompts", type=Path, metavar="DIR")
    io.add_argument("--import-responses", type=Path, metavar="DIR")
    parser.add_argument(
        "--responder",
        metavar="KIND:DETAIL",
        help="who answered the imported requests (required with --import-responses)",
    )
    return parser


# --- providers and sessions ----------------------------------------------------------


def resolver_provider(name: str, api_key: str, models: dict[str, str]) -> LLMProvider:
    """The provider instance the app uses for the resolver (no catalog: its default)."""
    if "resolver" in models:
        return get_provider(name, api_key=api_key, model=models["resolver"])
    session = LLMSession(name, api_key, user_id=None)
    return session.provider_for(Purpose.IDENTITY)


def identity_providers(
    name: str, api_key: str, catalog, models: dict[str, str]
) -> dict[Purpose, LLMProvider]:
    """The provider instance of each identity purpose: the catalog's model of its role
    (`identity`, `identity_strong`), as the app picks it, unless `models` names one."""
    session = LLMSession(name, api_key, catalog=catalog, user_id=None)
    providers = {}
    for purpose in (Purpose.IDENTITY, Purpose.IDENTITY_STRONG):
        model = models.get(purpose.value)
        providers[purpose] = (
            get_provider(
                name, api_key=api_key, model=model, profile=catalog.profile(name, model)
            )
            if model
            else session.provider_for(purpose)
        )
    return providers


async def _api_key(provider: str) -> str:
    from config import get_settings
    from scripts.refresh_model_catalog import resolve_keys

    keys = await resolve_keys(get_settings(), [provider], None)
    if provider not in keys:
        raise SystemExit(f"no API key for {provider}")
    return keys[provider]


# --- legacy -----------------------------------------------------------------------------


async def _emit(selection: runner.Selection, like: LLMProvider, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for scene in selection.requests:
        request = await build_request(scene, like)
        if request is not None:
            (out / f"{scene.id}.json").write_text(dumps_request(request), "utf-8")
            written += 1
    skipped = len(selection.requests) - written
    print(f"[eval] {written} requests written to {out} ({skipped} without reference)")
    return 0


async def _import_sessions(selection: runner.Selection, like: LLMProvider, src: Path):
    """Replay session per selected scene; SystemExit if one that the app would resolve
    has no emitted request or no response file."""
    called = [s.id for s in selection.requests if (await reference(s)).text]
    no_request = [i for i in called if not (src / f"{i}.json").is_file()]
    if no_request:
        raise SystemExit(f"--import-responses: no request for {', '.join(no_request)}")
    no_response = [i for i in called if not (src / f"{i}.txt").is_file()]
    if no_response:
        raise SystemExit(
            f"--import-responses: no response for {', '.join(no_response)}"
        )

    def session_for(scene_id: str) -> LLMSession | None:
        path = src / f"{scene_id}.txt"
        raw = path.read_text(encoding="utf-8") if path.is_file() else ""
        return replay_session(like, raw)

    return session_for


async def _run_legacy(
    args: argparse.Namespace, selection: runner.Selection, models: dict[str, str]
) -> int:
    adapter = LegacyResolverAdapter()
    like = resolver_provider(args.provider, OFFLINE_KEY, models)
    if args.emit_prompts:
        return await _emit(selection, like, args.emit_prompts)
    if args.import_responses:
        if args.runs != 1:
            raise SystemExit("--import-responses holds one run: use --runs 1")
        session_for = await _import_sessions(selection, like, args.import_responses)
    else:
        api_key = await _api_key(args.provider)
        session = LLMSession.from_provider(
            resolver_provider(args.provider, api_key, models)
        )

        def session_for(_scene_id: str) -> LLMSession:
            return session

    scores_by_run, sequences_by_run = [], []
    for _ in range(args.runs):
        results = await runner.run_scenes(adapter, selection.scenes, session_for)
        scores_by_run.append(runner.score(selection.scenes, results))
        if selection.sequences:
            sequences_by_run.append(
                await runner.run_sequences(adapter, selection.sequences, session_for)
            )
    return await _report(
        args,
        adapter,
        scores_by_run,
        {"resolver": like.model_name(Purpose.IDENTITY.value), **models},
        sequence_results_by_run=sequences_by_run,
    )


# --- v2 ---------------------------------------------------------------------------------


async def _eval_pool():
    """A pool on TEST_DATABASE_URL (a database named *_test only), language packs synced
    (the normalisation SQL reads them)."""
    import asyncpg

    from repos.pool import init_connection
    from scripts.sync_lang_packs import ensure_and_sync

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise SystemExit(
            "--adapter v2 needs TEST_DATABASE_URL (scripts/eval-identity.sh starts one)"
        )
    if not urlparse(url).path.lstrip("/").endswith("_test"):
        raise SystemExit("TEST_DATABASE_URL: the database name must end with _test")

    pool = await asyncpg.create_pool(url, min_size=1, max_size=2, init=init_connection)
    async with pool.acquire() as conn:
        await ensure_and_sync(conn)
    return pool


def run_directory(base: Path, run: int, runs: int) -> Path:
    """The responses directory of run `run` (0-based): `base`, or `base/run<n>`."""
    return base if runs == 1 else base / f"run{run + 1}"


async def _tapped_run(
    adapter,
    scenes,
    providers: dict[Purpose, LLMProvider],
    new_tap: Callable[[str], Tap],
):
    """One run of the scenes, each scene's calls on its own tap: (results, taps)."""
    taps: dict[str, Tap] = {}

    def session_for(scene_id: str) -> LLMSession:
        taps[scene_id] = new_tap(scene_id)
        return tapped_session(providers, taps[scene_id])

    results = await runner.run_scenes(adapter, scenes, session_for)
    return results, taps


def _print_pending(base: Path, pending) -> None:
    index = write_pending_index(base, pending)
    counts = Counter(p.purpose for p in pending)
    per_purpose = ", ".join(f"{purpose} {n}" for purpose, n in sorted(counts.items()))
    print(f"[eval] {len(pending)} requests pending ({per_purpose or 'none'}): {index}")


async def _v2_runs(args, adapter, scenes, providers):
    """(results, taps) of every run, and the pending requests of the staged replay."""
    base = args.emit_prompts or args.import_responses
    runs, pending = [], []
    for run in range(args.runs):
        if base is None:
            runs.append(await _tapped_run(adapter, scenes, providers, Tap))
            continue
        responses = Responses(run_directory(base, run, args.runs))
        runs.append(await _tapped_run(adapter, scenes, providers, responses.tap))
        if responses.stale:
            write_pending_index(base, [])  # nothing to answer until the stale ones go
            raise SystemExit(
                f"stale answers in {responses.directory}: {', '.join(responses.stale)} "
                "answer another request than the one now built; remove them and their "
                "later calls, then answer again"
            )
        pending += responses.pending
    if base is not None:
        _print_pending(base, pending)
    return runs, pending


async def _cheap_replay(args, pool, scenes, providers):
    """The cheap tier on the cascade's own answers (the small model's, same samples):
    its scores per run, or None when a run would need a request the cascade never made
    (nothing is written in the cascade's directory)."""
    adapter = ResolverV2Adapter(pool, tier="cheap")
    scores = []
    for run in range(args.runs):
        directory = run_directory(args.import_responses, run, args.runs)
        responses = Responses(directory, write=False)
        results, _ = await _tapped_run(adapter, scenes, providers, responses.tap)
        if responses.pending or responses.stale:
            print("[eval] cheap tier not replayable from these answers: not reported")
            return None
        scores.append(runner.score(scenes, results))
    return scores


async def _run_v2(
    args: argparse.Namespace, selection: runner.Selection, models: dict[str, str]
) -> int:
    if selection.sequences:
        raise SystemExit("--adapter v2 runs scenes only (no --sequences yet)")
    from repos.llm_models import load_catalog

    staged = bool(args.emit_prompts or args.import_responses)
    pool = await _eval_pool()
    try:
        adapter = ResolverV2Adapter(pool, tier=args.tier)
        key = OFFLINE_KEY if staged else await _api_key(args.provider)
        providers = identity_providers(
            args.provider, key, await load_catalog(pool), models
        )
        runs, pending = await _v2_runs(args, adapter, selection.scenes, providers)
        if args.emit_prompts:
            return 0
        if pending:
            print("[eval] nothing scored: answer the pending requests, then run again")
            return PENDING_EXIT
        purposes = [Purpose.IDENTITY]
        extra = {}
        if args.tier == "cascade":
            purposes.append(Purpose.IDENTITY_STRONG)
            if args.import_responses:
                extra["cheap_scores_by_run"] = await _cheap_replay(
                    args, pool, selection.scenes, providers
                )
        return await _report(
            args,
            adapter,
            [runner.score(selection.scenes, results) for results, _ in runs],
            {p.value: providers[p].model_name(p.value) for p in purposes},
            cost_estimated=staged,
            leaks_by_run=[
                sum(
                    leak_count(s, taps[s.id].card_lines(), taps[s.id].texts())
                    for s in selection.scenes
                )
                for _, taps in runs
            ],
            **extra,
        )
    finally:
        await pool.close()


# --- report -------------------------------------------------------------------------------


async def _report(args, adapter, scores_by_run, models: dict[str, str], **extra) -> int:
    notes = [import_note(args.responder)] if args.import_responses else []
    if args.import_responses and args.tier == "cheap":
        cascade = holds_purpose(args.import_responses, Purpose.IDENTITY_STRONG)
        notes.append(CHEAP_REPLAY_NOTE if cascade else CHEAP_NOTE)
    if extra.get("sequence_results_by_run"):
        notes.append(adapter.sequence_note)
    if adapter.candidates_note:
        notes.append(adapter.candidates_note)
    markdown, data = runner.build_report(
        scores_by_run,
        provider=args.provider,
        models=models,
        split=args.split,
        header_note=" ".join(n for n in notes if n),
        responder=args.responder if args.import_responses else None,
        c_at_10_scores=await runner.blocking_scores(adapter, args.root),
        iterations=args.iterations,
        cost_priced=not any(is_unpriced(args.provider, m) for m in models.values()),
        milestone=args.milestone,
        **extra,
    )
    date = datetime.date.today().isoformat()
    name = runner.report_name(
        date, args.split, args.provider, models, data.get("responder")
    )
    path = runner.write_report(args.out, name, markdown, data)
    print(f"[eval] report written to {path}")
    passed = data["milestone"]["passed"] if args.milestone else data["gate_passed"]
    return 1 if args.gate and not passed else 0


async def _run(args: argparse.Namespace) -> int:
    if args.needs_db:
        print(int(ADAPTERS[args.adapter].needs_db))
        return 0
    if args.import_responses and not args.responder:
        raise SystemExit("--import-responses needs --responder KIND:DETAIL")
    models = _parse_models(args.models, args.adapter)
    selection = runner.select(
        args.root,
        args.split,
        category=args.category,
        scene_id=args.scene,
        sequences=args.sequences,
    )
    if not selection.scenes:
        raise SystemExit("no scene selected")
    if args.adapter == "v2":
        return await _run_v2(args, selection, models)
    return await _run_legacy(args, selection, models)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
