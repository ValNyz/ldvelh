"""Write the dev/test split of the identity corpus and freeze the test fingerprint (#151).

The split is stratified by each scene's dominant category (evals/identity/split.py) and
written to tests/fixtures/identity/split.yaml. `--freeze` then writes TEST_SHA256, the
sha256 of the test scene files (corpus.fingerprint_test_split), checked by the CI.

While the corpus is being annotated, rerun it with `--freeze` after each new scene.
Once the corpus is complete the test split is frozen (D25): never re-split it; a gold
correction of a test scene goes in its own PR and refreshes only the fingerprint
(`--freeze --keep-split`).

Usage (from backend/):
  python -m scripts.identity_corpus_split --ratio 0.6 --seed 42
  python -m scripts.identity_corpus_split --ratio 0.6 --seed 42 --freeze
  python -m scripts.identity_corpus_split --freeze --keep-split
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
    args = parser.parse_args(argv)
    misnamed = corpus.file_name_errors(args.root)
    if misnamed:
        print("\n".join(misnamed), file=sys.stderr)
        return 1
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
