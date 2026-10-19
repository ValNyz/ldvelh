"""Evaluate a resolver on the identity gold corpus and write the report (#151).

Three ways to get the resolver's answers:

- live (default): real calls through the provider (`--provider`); the key comes from
  the server settings (ANTHROPIC_API_KEY...) or from the keys the player of
  CATALOG_KEYS_USER_EMAIL saved in the app;
- `--emit-prompts DIR`: no call; writes `<scene id>.json` per resolver request (model,
  options, system, messages), exactly what the app would send;
- `--import-responses DIR`: reads the raw model outputs `<scene id>.txt` answered to
  those requests elsewhere, parses them with the app's code and scores them.

The report goes to `<out>/<date>-<split>-<provider>-<models>.md|json`. With `--gate`
the exit code is 1 when a measured gate row fails.

Usage (from backend/, or through scripts/eval-identity.sh from the repo root):
  python -m scripts.eval_identity --adapter legacy --split test --runs 1 --provider anthropic
  python -m scripts.eval_identity --adapter legacy --split dev --sequences --emit-prompts DIR
  python -m scripts.eval_identity --adapter legacy --split dev --sequences --import-responses DIR
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import sys
from pathlib import Path

from evals.identity import runner
from evals.identity.adapters.legacy_resolver import (
    LegacyResolverAdapter,
    build_request,
    dumps_request,
    replay_session,
)
from evals.identity.corpus import Category
from llm.session import LLMSession, Purpose
from services.llm_providers import _CLASSES, LLMProvider, get_provider

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND / "tests" / "fixtures" / "identity"
OUT = BACKEND / "tests" / "reports" / "identity"
ADAPTERS = {"legacy": LegacyResolverAdapter}
OFFLINE_KEY = "offline"  # builds a provider client that never sends a request
IMPORT_NOTE = "Source: subagent responses (not the API path)."


def _parse_models(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    pairs = [item.split("=", 1) for item in text.split(",")]
    if any(len(p) != 2 or not all(p) for p in pairs):
        raise SystemExit(f"--models: expected role=model[,role=model], got {text!r}")
    return dict(pairs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--adapter", choices=sorted(ADAPTERS), default="legacy")
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--provider", choices=sorted(_CLASSES), default="anthropic")
    parser.add_argument("--models", help="resolver=MODEL (default: the app's choice)")
    parser.add_argument("--category", choices=Category.__args__)
    parser.add_argument("--scene", help="one scene id")
    parser.add_argument("--sequences", action="store_true", help="add the sequences")
    parser.add_argument("--gate", action="store_true", help="exit 1 if the gate fails")
    parser.add_argument("--root", type=Path, default=ROOT, help="corpus directory")
    parser.add_argument("--out", type=Path, default=OUT, help="report directory")
    parser.add_argument("--iterations", type=int, default=2000, help="bootstrap draws")
    io = parser.add_mutually_exclusive_group()
    io.add_argument("--emit-prompts", type=Path, metavar="DIR")
    io.add_argument("--import-responses", type=Path, metavar="DIR")
    return parser


def resolver_provider(name: str, api_key: str, models: dict[str, str]) -> LLMProvider:
    """The provider instance the app uses for the resolver (no catalog: its default)."""
    if "resolver" in models:
        return get_provider(name, api_key=api_key, model=models["resolver"])
    session = LLMSession(name, api_key, user_id=None)
    return session.provider_for(Purpose.RESOLVER)


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


def _import_sessions(selection: runner.Selection, like: LLMProvider, src: Path):
    """Replay session per scene id; SystemExit if a request has no response file."""
    expected = {p.stem for p in src.glob("*.json")}
    missing = sorted(i for i in expected if not (src / f"{i}.txt").is_file())
    if missing:
        raise SystemExit(f"--import-responses: no response for {', '.join(missing)}")
    wanted = {s.id for s in selection.requests}
    absent = sorted(wanted - expected)
    if absent:
        print(f"[eval] no request emitted (no reference) for {len(absent)} scenes")

    def session_for(scene_id: str) -> LLMSession | None:
        path = src / f"{scene_id}.txt"
        raw = path.read_text(encoding="utf-8") if path.is_file() else ""
        return replay_session(like, raw)

    return session_for


async def _live_session(provider: str, models: dict[str, str]) -> LLMSession:
    from config import get_settings
    from scripts.refresh_model_catalog import resolve_keys

    keys = await resolve_keys(get_settings(), [provider], None)
    if provider not in keys:
        raise SystemExit(f"no API key for {provider}")
    return LLMSession.from_provider(resolver_provider(provider, keys[provider], models))


async def _run(args: argparse.Namespace) -> int:
    models = _parse_models(args.models)
    selection = runner.select(
        args.root,
        args.split,
        category=args.category,
        scene_id=args.scene,
        sequences=args.sequences,
    )
    if not selection.scenes:
        raise SystemExit("no scene selected")
    adapter = ADAPTERS[args.adapter]()
    like = resolver_provider(args.provider, OFFLINE_KEY, models)
    if args.emit_prompts:
        return await _emit(selection, like, args.emit_prompts)
    note = ""
    if args.import_responses:
        if args.runs != 1:
            raise SystemExit("--import-responses holds one run: use --runs 1")
        session_for = _import_sessions(selection, like, args.import_responses)
        note = IMPORT_NOTE
    else:
        session = await _live_session(args.provider, models)

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
    models = {"resolver": like.model_name(Purpose.RESOLVER.value), **models}
    markdown, data = runner.build_report(
        scores_by_run,
        provider=args.provider,
        models=models,
        split=args.split,
        header_note=note,
        sequence_results_by_run=sequences_by_run,
        c_at_10_scores=await runner.blocking_scores(adapter, args.root),
        iterations=args.iterations,
    )
    date = datetime.date.today().isoformat()
    name = runner.report_name(date, args.split, args.provider, models)
    path = runner.write_report(args.out, name, markdown, data)
    print(f"[eval] report written to {path}")
    return 1 if args.gate and not data["gate_passed"] else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
