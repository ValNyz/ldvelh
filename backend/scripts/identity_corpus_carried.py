"""Write the « carried by the protagonist » flag of the identity corpus worlds (#154, R39).

Applies the one rule of `evals/identity/carried.py` to every scene and sequence turn of
the corpus and writes `carried: true` under each object it selects (and removes any other
`carried:` line), keeping the files as they are otherwise. `--check` writes nothing and
exits 1 when a file differs from the rule. Reports counts per split only.

  python -m scripts.identity_corpus_carried [--root DIR] [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from evals.identity.carried import carried_objects
from evals.identity.corpus import Scene, load_scenes, load_sequences, load_split

ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "identity"
_ENTRY = re.compile(r"^(?P<indent>\s*)- id: (?P<id>\S+)\s*$")
_CARRIED = re.compile(r"^\s*carried:\s*\S+\s*$")
OBJECT_LINE = "type: object"


def flagged(lines: list[str], carried_by_block, turn_indent: str | None) -> list[str]:
    """`lines` with `carried: true` under the objects `carried_by_block(turn id)` names;
    `turn_indent`: the indent of a sequence's turn entries (None for a scene file)."""
    out: list[str] = []
    turn: str | None = None
    entity: tuple[str, str] | None = None  # (indent, id) of the entity being read
    for line in lines:
        if _CARRIED.match(line):
            continue
        out.append(line)
        match = _ENTRY.match(line.rstrip("\n"))
        if match and turn_indent is not None and match["indent"] == turn_indent:
            turn, entity = match["id"], None
            continue
        if match:
            entity = (match["indent"], match["id"])
            continue
        if entity and line.strip() == OBJECT_LINE:
            indent, entity_id = entity
            if entity_id in carried_by_block(turn):
                out.append(f"{indent}  carried: true\n")
            entity = None
    return out


def _scene_lines(path: Path, scene: Scene) -> list[str]:
    carried = carried_objects(scene)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return flagged(lines, lambda _turn: carried, None)


def apply(root: Path, *, check: bool) -> tuple[dict[str, int], list[str]]:
    """(objects flagged per split, files that differ from the rule)."""
    split = load_split(root)
    side = {i: "dev" for i in split.dev} | {i: "test" for i in split.test}
    counts = {"dev": 0, "test": 0, "sequences": 0}
    changed = []
    for scene in load_scenes(root):
        path = root / "scenes" / f"{scene.id}.yaml"
        new = "".join(_scene_lines(path, scene))
        if scene.id in side:
            counts[side[scene.id]] += len(carried_objects(scene))
        changed += _write(path, new, check)
    for sequence in load_sequences(root):
        path = root / "sequences" / f"{sequence.id}.yaml"
        by_turn = {t.id: carried_objects(t) for t in sequence.turns}
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        new = "".join(flagged(lines, lambda turn: by_turn.get(turn, set()), ""))
        counts["sequences"] += sum(len(v) for v in by_turn.values())
        changed += _write(path, new, check)
    return counts, changed


def _write(path: Path, new: str, check: bool) -> list[str]:
    if path.read_text(encoding="utf-8") == new:
        return []
    if not check:
        path.write_text(new, encoding="utf-8")
    return [path.name]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="write nothing")
    args = parser.parse_args(argv)
    counts, changed = apply(args.root, check=args.check)
    print(
        f"carried objects: {counts}; files {'to change' if args.check else 'changed'}: "
        f"{len(changed)}"
    )
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    sys.exit(main())
