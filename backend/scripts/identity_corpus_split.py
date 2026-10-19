"""Write the dev/test split of the identity corpus and freeze the test fingerprint (#151).

The split moves whole campaigns (`Scene.campaign`) so that each category keeps about
`1 - ratio` of its mentions in test (evals/identity/split.py), and is written to
tests/fixtures/identity/split.yaml. `--freeze` then writes TEST_SHA256, the sha256 of
the test scene files (corpus.fingerprint_test_split), checked by the CI.

While the corpus is being annotated, rerun it with `--freeze` after each new scene.
Once the corpus is complete the test split is frozen (D25): never re-split it.
- A gold correction of a test scene goes in its own PR and refreshes only the
  fingerprint (`--freeze --keep-split`).
- A new scene goes to dev with `--add-dev ID...`: appended to the dev list, the test
  list and TEST_SHA256 untouched. It is refused if its campaign has a test scene
  (the new scene's history would show test gold on the dev side).

Usage (from backend/):
  python -m scripts.identity_corpus_split --ratio 0.6 --seed 42
  python -m scripts.identity_corpus_split --ratio 0.6 --seed 42 --freeze
  python -m scripts.identity_corpus_split --freeze --keep-split
  python -m scripts.identity_corpus_split --add-dev syn-sf-new-06 syn-sf-new-07
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from evals.identity import corpus
from evals.identity.corpus import Split, load_scenes, load_split
from evals.identity.split import shares_in_test, stratified_split

ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "identity"


def _header(ratio: float, seed: int) -> str:
    return (
        "# Dev/test split of the identity corpus (generated, do not edit by hand):\n"
        f"# python -m scripts.identity_corpus_split --ratio {ratio} --seed {seed}\n"
        "# Frozen with TEST_SHA256 once the corpus is complete (D25).\n"
    )


def write_split(root: Path, split: Split, *, ratio: float, seed: int) -> None:
    body = yaml.safe_dump(split.model_dump(), allow_unicode=True, sort_keys=False)
    (root / "split.yaml").write_text(_header(ratio, seed) + body, encoding="utf-8")


def add_dev(root: Path, scene_ids: list[str]) -> list[str]:
    """Append new scenes to dev, keeping split.yaml's header; errors as lines (none = done)."""
    split = load_split(root)
    scenes = {s.id: s for s in load_scenes(root)}
    test_campaigns = {scenes[i].campaign for i in split.test if i in scenes}
    errors = []
    for scene_id in scene_ids:
        if scene_id not in scenes:
            errors.append(f"{scene_id}: no scene file scenes/{scene_id}.yaml")
        elif scene_id in split.dev or scene_id in split.test:
            errors.append(f"{scene_id}: already in the split")
        elif scenes[scene_id].campaign in test_campaigns:
            errors.append(
                f"{scene_id}: campaign {scenes[scene_id].campaign!r} has test scenes"
            )
    if errors:
        return errors
    path = root / "split.yaml"
    header = "".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
        if line.startswith("#")
    )
    grown = Split(dev=sorted({*split.dev, *scene_ids}), test=split.test)
    body = yaml.safe_dump(grown.model_dump(), allow_unicode=True, sort_keys=False)
    path.write_text(header + body, encoding="utf-8")
    return []


def write_fingerprint(root: Path) -> str:
    fingerprint = corpus.fingerprint_test_split(root)
    (root / "TEST_SHA256").write_text(fingerprint + "\n", encoding="utf-8")
    return fingerprint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--ratio", type=float, default=0.6, help="dev share")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--freeze", action="store_true", help="write TEST_SHA256")
    parser.add_argument(
        "--keep-split", action="store_true", help="keep split.yaml as it is"
    )
    parser.add_argument(
        "--add-dev", nargs="+", metavar="ID", help="append new scenes to dev only"
    )
    args = parser.parse_args(argv)
    misnamed = corpus.file_name_errors(args.root)
    if misnamed:
        print("\n".join(misnamed), file=sys.stderr)
        return 1
    if args.add_dev:
        errors = add_dev(args.root, args.add_dev)
        print("\n".join(errors or [f"added to dev: {' '.join(args.add_dev)}"]))
        return 1 if errors else 0
    scenes = load_scenes(args.root)
    if args.keep_split:
        split = load_split(args.root)
    else:
        split = stratified_split(scenes, ratio=args.ratio, seed=args.seed)
        write_split(args.root, split, ratio=args.ratio, seed=args.seed)
    print(f"{len(split.dev)} dev scenes, {len(split.test)} test scenes")
    for category, (in_test, total) in shares_in_test(scenes, split).items():
        print(f"  {category:<7} {in_test:>4}/{total:<4} mentions in test")
    if args.freeze:
        print(f"TEST_SHA256 {write_fingerprint(args.root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
