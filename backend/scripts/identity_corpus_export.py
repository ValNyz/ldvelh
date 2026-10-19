"""Export the skeleton scenes of a real game for the identity gold corpus (#151).

One scene per assistant turn: `world` = the game's entities with symbolic ids
`<type>_<slug>`, `history` = the K = 6 previous assistant messages with their
`narrator_context` turned into mentions TO REVIEW, `narration` = the turn's text,
`gold` empty. The skeleton is a starting point: the annotator corrects the world
(duplicates, invented canonicals, missing entities) and writes the gold by hand,
following tests/fixtures/identity/ANNOTATION.md. Existing files are never overwritten
(an annotated scene is precious) unless `--force` is given.

The database is only read: the session is put in `default_transaction_read_only`.
When the database cannot be reached directly, `--print-sql` writes the dump query
(one JSON object per game) to run through psql, and `--from-json` reads its output.

`--export-surfaces <split>` writes surfaces-only/<id>.yaml for every scene of the
split (narration and mention surfaces, no decision) for the delayed blind review.

Usage (from backend/):
  DATABASE_URL=postgresql://… python -m scripts.identity_corpus_export --game <id> \
      --genre <genre> [--language <lexicon>]     (or --database-url, visible in ps)
  python -m scripts.identity_corpus_export --print-sql --game <id> > dump.sql
  python -m scripts.identity_corpus_export --from-json dump.json --game <id> --genre <genre>
  python -m scripts.identity_corpus_export --export-surfaces test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
import uuid
from pathlib import Path

import yaml

from evals.identity.lexicon import DEFAULT_LANGUAGE, Lexicon, load_lexicon

ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "identity"
HISTORY_SIZE = 6

# One JSON object per game; `{game}` is a validated UUID.
DUMP_SQL = """SET default_transaction_read_only = on;
\\pset pager off
\\t on
\\pset format unaligned
SELECT json_build_object(
 'game', (SELECT row_to_json(g) FROM (SELECT id, name, character_data FROM games
          WHERE id = '{game}') g),
 'registry', (SELECT json_agg(r) FROM (SELECT entity_type, name FROM entity_registry
              WHERE game_id = '{game}' ORDER BY entity_type, name) r),
 'companions', (SELECT json_agg(c) FROM (SELECT name, voice FROM companions
                WHERE game_id = '{game}') c),
 'characters', (SELECT json_agg(c ORDER BY c.created_at) FROM (SELECT id, name,
                descriptor, known_by_protagonist, occupation, workplace_id,
                residence_id, created_at FROM characters WHERE game_id = '{game}'
                AND removed_cycle IS NULL) c),
 'locations', (SELECT json_agg(l ORDER BY l.created_at) FROM (SELECT id, name,
               location_type, parent_id, created_at FROM locations
               WHERE game_id = '{game}' AND removed_cycle IS NULL) l),
 'organizations', (SELECT json_agg(o ORDER BY o.created_at) FROM (SELECT id, name,
                   org_type, created_at FROM organizations WHERE game_id = '{game}'
                   AND removed_cycle IS NULL) o),
 'objects', (SELECT json_agg(x ORDER BY x.created_at) FROM (SELECT id, name,
             category, created_at FROM objects
             WHERE game_id = '{game}' AND removed_cycle IS NULL) x),
 'arcs', (SELECT json_agg(a ORDER BY a.created_at) FROM (SELECT title, description,
          created_at FROM narrative_arcs WHERE game_id = '{game}') a),
 'facts', (SELECT json_agg(f ORDER BY f.created_at) FROM (SELECT description,
           created_at FROM facts WHERE game_id = '{game}') f),
 'messages', (SELECT json_agg(m ORDER BY m.created_at, m.sequence) FROM (SELECT role,
              sequence, content, location_id, narrator_context,
              narrator_deltas -> 'entity_reveals' AS entity_reveals, created_at
              FROM messages WHERE game_id = '{game}') m)
);
"""

_QUERIES = {
    "game": "SELECT id, name, character_data FROM games WHERE id = $1",
    "registry": "SELECT entity_type, name FROM entity_registry WHERE game_id = $1"
    " ORDER BY entity_type, name",
    "companions": "SELECT name, voice FROM companions WHERE game_id = $1",
    "characters": "SELECT id, name, descriptor, known_by_protagonist, occupation,"
    " workplace_id, residence_id FROM characters WHERE game_id = $1"
    " AND removed_cycle IS NULL ORDER BY created_at",
    "locations": "SELECT id, name, location_type, parent_id FROM locations"
    " WHERE game_id = $1 AND removed_cycle IS NULL ORDER BY created_at",
    "organizations": "SELECT id, name, org_type FROM organizations WHERE game_id = $1"
    " AND removed_cycle IS NULL ORDER BY created_at",
    "objects": "SELECT id, name, category FROM objects"
    " WHERE game_id = $1 AND removed_cycle IS NULL ORDER BY created_at",
    "arcs": "SELECT title, description FROM narrative_arcs WHERE game_id = $1"
    " ORDER BY created_at",
    "facts": "SELECT description FROM facts WHERE game_id = $1 ORDER BY created_at",
    "messages": "SELECT role, sequence, content, location_id, narrator_context,"
    " narrator_deltas -> 'entity_reveals' AS entity_reveals FROM messages"
    " WHERE game_id = $1 ORDER BY created_at, sequence",
}


# --- pure conversion ---------------------------------------------------------


def slugify(label: str, lexicon: Lexicon) -> str:
    """`La Kethari âgée` -> `kethari_agee`: lower case, no accents, no leading determiner."""
    text = lexicon.strip_determiner(label).casefold()
    plain = "".join(
        c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")


def entity_id(entity_type: str, label: str, lexicon: Lexicon) -> str:
    return f"{entity_type}_{slugify(label, lexicon)}"


def _alias(text: str, kind: str, known: bool) -> dict:
    return {"text": text, "kind": kind, "known": known}


def _entity(entity_type: str, label: str, lexicon: Lexicon, **fields) -> dict:
    return {
        "id": entity_id(entity_type, label, lexicon),
        "type": entity_type,
        "label": label,
        "true_name": fields.get("true_name"),
        "descriptor": fields.get("descriptor"),
        "known": fields.get("known", True),
        "occupation": fields.get("occupation"),
        "location": fields.get("location"),
        "last_seen_turn": None,
        "aliases": fields.get("aliases", []),
    }


def _character(row: dict, location_ids: dict[str, str], lexicon: Lexicon) -> dict:
    name, descriptor = row["name"], row.get("descriptor")
    known = bool(row.get("known_by_protagonist"))
    aliases = [_alias(name, "true_name", known)]
    parts = name.split()
    if len(parts) > 1:  # derived short forms (first and last word)
        aliases += [_alias(parts[0], "short", known), _alias(parts[-1], "short", known)]
    if descriptor and descriptor != name:
        aliases.append(_alias(descriptor, "descriptor", True))
    place = row.get("workplace_id") or row.get("residence_id")
    return _entity(
        "character",
        name,
        lexicon,
        true_name=name,
        descriptor=descriptor,
        known=known,
        occupation=row.get("occupation") or None,
        location=location_ids.get(str(place)) if place else None,
        aliases=aliases,
    )


def _thing(entity_type: str, name: str, lexicon: Lexicon) -> dict:
    return _entity(entity_type, name, lexicon, aliases=[_alias(name, "label", True)])


def _protagonist_name(dump: dict) -> str:
    data = (dump.get("game") or {}).get("character_data") or {}
    if isinstance(data, str):
        data = json.loads(data) if data.strip() else {}
    if data.get("name"):
        return data["name"]
    rows = dump.get("registry") or []
    name = next((r["name"] for r in rows if r["entity_type"] == "protagonist"), None)
    if not name:
        raise ValueError("the dump names no protagonist (character_data or registry)")
    return name


def _location_ids(dump: dict, lexicon: Lexicon) -> dict[str, str]:
    return {
        str(r["id"]): entity_id("location", r["name"], lexicon)
        for r in dump.get("locations") or []
    }


def build_world(dump: dict, lexicon: Lexicon) -> list[dict]:
    """World skeleton: protagonist, companion, characters, locations, organizations, objects, arcs."""
    hero = _protagonist_name(dump)
    location_ids = _location_ids(dump, lexicon)
    world = [
        _entity(
            "protagonist",
            hero,
            lexicon,
            true_name=hero,
            aliases=[_alias(hero, "true_name", True)],
        )
    ]
    world += [
        _entity(
            "companion",
            r["name"],
            lexicon,
            true_name=r["name"],
            aliases=[_alias(r["name"], "true_name", True)],
        )
        for r in dump.get("companions") or []
    ]
    world += [
        _character(r, location_ids, lexicon) for r in dump.get("characters") or []
    ]
    for key, entity_type in (
        ("locations", "location"),
        ("organizations", "organization"),
        ("objects", "object"),
    ):
        world += [_thing(entity_type, r["name"], lexicon) for r in dump.get(key) or []]
    world += [
        _entity("arc", r["title"], lexicon, known=False) for r in dump.get("arcs") or []
    ]  # arc titles are Director-side: the PC knows no name of an arc
    return world


def _name_index(world: list[dict], lexicon: Lexicon) -> dict[tuple[str, str], str]:
    """(type, normalized name or alias) -> entity id, to resolve old canonicals."""
    index: dict[tuple[str, str], str] = {}
    for entity in world:
        person = entity["type"] in ("protagonist", "companion")
        entity_type = "character" if person else entity["type"]
        for text in [entity["label"]] + [a["text"] for a in entity["aliases"]]:
            index.setdefault((entity_type, slugify(text, lexicon)), entity["id"])
    return index


def resolve_canonical(
    index: dict[tuple[str, str], str],
    canonical: str,
    entity_type: str,
    lexicon: Lexicon,
) -> str:
    """Id of the world entity an old resolver canonical names (or its would-be id)."""
    return index.get(
        (entity_type, slugify(canonical, lexicon)),
        entity_id(entity_type, canonical, lexicon),
    )


def context_to_mentions(
    text: str,
    context: list | None,
    index: dict[tuple[str, str], str],
    lexicon: Lexicon,
) -> list[dict]:
    """Old `narrator_context` spans -> history mentions TO REVIEW (MATCH, category guessed).

    Personal pronouns are dropped (never mentions); of two spans at the same start
    the longest is kept. An unresolved canonical keeps a would-be id that is not in
    the world, so that validation flags it for the annotator.
    """
    spans: dict[int, tuple[int, str, str]] = {}
    for start, end, canonical, entity_type in context or []:
        if start in spans and spans[start][0] >= end:
            continue
        spans[start] = (end, canonical, entity_type)
    mentions = []
    for start in sorted(spans):
        end, canonical, entity_type = spans[start]
        surface = text[start:end]
        if not surface.strip() or lexicon.key(surface) in lexicon.personal_pronouns:
            continue
        target = resolve_canonical(index, canonical, entity_type, lexicon)
        mentions.append(
            {
                "surface": surface,
                "start": start,
                "category": "EASY"
                if slugify(surface, lexicon) == slugify(canonical, lexicon)
                else "DESC",
                "expected": f"MATCH {target}",
            }
        )
    return mentions


def _assistant_turns(dump: dict) -> list[dict]:
    return [m for m in dump.get("messages") or [] if m["role"] == "assistant"]


def _mentioned_ids(
    message: dict, index: dict[tuple[str, str], str], lexicon: Lexicon
) -> set[str]:
    return {
        resolve_canonical(index, canonical, entity_type, lexicon)
        for _, _, canonical, entity_type in message.get("narrator_context") or []
    }


def _knowledge(world: list[dict]) -> list[dict]:
    return [
        {"ref": e["id"], "kind": "name", "state": "unknown", "text": e["true_name"]}
        for e in world
        if not e["known"] and e["true_name"]
    ]


def build_scene(
    dump: dict,
    turn: int,
    game_prefix: str,
    *,
    genre: str,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    """Skeleton scene of the `turn`-th assistant message (1-based)."""
    lexicon = load_lexicon(language)
    turns = _assistant_turns(dump)
    message = turns[turn - 1]
    world = build_world(dump, lexicon)
    index = _name_index(world, lexicon)
    for entity in world:  # last turn before this one where the old resolver tagged it
        seen = [
            n
            for n, m in enumerate(turns[: turn - 1], start=1)
            if entity["id"] in _mentioned_ids(m, index, lexicon)
        ]
        entity["last_seen_turn"] = seen[-1] if seen else None
    history = [
        {
            "text": m["content"],
            "mentions": context_to_mentions(
                m["content"], m.get("narrator_context"), index, lexicon
            ),
        }
        for m in turns[max(0, turn - 1 - HISTORY_SIZE) : turn - 1]
    ]
    location_ids = _location_ids(dump, lexicon)
    return {
        "id": f"real-{game_prefix}-t{turn:02d}",
        "genre": genre,
        "campaign": f"real-{game_prefix}",
        "language": language,
        "source": "real",
        "turn": turn,
        "world": world,
        "history": history,
        "scene": {
            "location": location_ids.get(str(message.get("location_id")), ""),
            "present": [
                e["id"] for e in world if e["type"] in ("protagonist", "companion")
            ],
            "reveals": [
                {"ref": r.get("current_name", ""), "real_name": r.get("real_name")}
                for r in message.get("entity_reveals") or []
            ],
            "planned_npcs": [],
            "secrets": [],
            "open_disclosures": [],
        },
        "narration": message["content"],
        "gold": [],
        "gold_effects": {"reveals": [], "merges": [], "forbidden_merges": []},
        "gold_knowledge": _knowledge(world),
    }


def unresolved_canonicals(dump: dict, lexicon: Lexicon) -> list[str]:
    """Old resolver canonicals that name no world entity (invented or missing)."""
    index = _name_index(build_world(dump, lexicon), lexicon)
    found = {
        f"{canonical} ({entity_type})"
        for m in _assistant_turns(dump)
        for _, _, canonical, entity_type in m.get("narrator_context") or []
        if (entity_type, slugify(canonical, lexicon)) not in index
    }
    return sorted(found)


def surfaces_only(scene: dict) -> dict:
    """Narration and mention surfaces without any decision (blind review)."""
    return {
        "id": scene["id"],
        "narration": scene["narration"],
        "mentions": [
            {"surface": m["surface"], "start": m["start"]} for m in scene["gold"]
        ],
    }


# --- I/O -----------------------------------------------------------------------


def dump_yaml(data: dict, header: str = "") -> str:
    return header + yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, width=100_000
    )


async def fetch_dump(database_url: str, game: str) -> dict:
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute("SET default_transaction_read_only = on")
        dump: dict = {}
        for key, query in _QUERIES.items():
            rows = [dict(r) for r in await conn.fetch(query, uuid.UUID(game))]
            for row in rows:
                for field in ("narrator_context", "entity_reveals", "character_data"):
                    if isinstance(row.get(field), str):
                        row[field] = json.loads(row[field])
            dump[key] = rows[0] if key == "game" and rows else rows
        return dump
    finally:
        await conn.close()


def write_scenes(
    dump: dict,
    game: str,
    out: Path,
    *,
    force: bool,
    genre: str,
    language: str = DEFAULT_LANGUAGE,
) -> list[Path]:
    prefix = game.replace("-", "")[:4]
    missing = unresolved_canonicals(dump, load_lexicon(language))
    header = (
        "# Skeleton exported by scripts/identity_corpus_export.py: review the world,\n"
        "# the history mentions and write the gold by hand (ANNOTATION.md).\n"
    )
    if missing:
        header += "# Unresolved old canonicals: " + "; ".join(missing) + "\n"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for turn in range(1, len(_assistant_turns(dump)) + 1):
        scene = build_scene(dump, turn, prefix, genre=genre, language=language)
        path = out / f"{scene['id']}.yaml"
        if path.exists() and not force:
            print(f"skip {path} (exists; --force to overwrite)", file=sys.stderr)
            continue
        path.write_text(dump_yaml(scene, header), encoding="utf-8")
        written.append(path)
    return written


def export_surfaces(root: Path, split_name: str) -> list[Path]:
    split = yaml.safe_load((root / "split.yaml").read_text(encoding="utf-8")) or {}
    out = root / "surfaces-only"
    out.mkdir(exist_ok=True)
    written = []
    for scene_id in split.get(split_name) or []:
        scene = yaml.safe_load(
            (root / "scenes" / f"{scene_id}.yaml").read_text(encoding="utf-8")
        )
        path = out / f"{scene_id}.yaml"
        path.write_text(dump_yaml(surfaces_only(scene)), encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--database-url", help="prefer the DATABASE_URL variable (not shown by ps)"
    )
    parser.add_argument("--game", help="game id (UUID)")
    parser.add_argument("--out", type=Path, default=ROOT / "scenes", help="directory")
    parser.add_argument("--from-json", type=Path, help="psql dump of --print-sql")
    parser.add_argument("--print-sql", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite scenes")
    parser.add_argument("--export-surfaces", metavar="SPLIT", choices=("dev", "test"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--genre", help="genre label of the game's scenes")
    parser.add_argument(
        "--language", default=DEFAULT_LANGUAGE, help="lexicon of the scenes"
    )
    args = parser.parse_args(argv)
    if args.export_surfaces:
        for path in export_surfaces(args.root, args.export_surfaces):
            print(path)
        return 0
    if not args.game:
        parser.error("--game is required")
    if not args.genre and not args.print_sql:
        parser.error("--genre is required")
    load_lexicon(args.language)  # fails early on a language without a lexicon
    game = str(uuid.UUID(args.game))  # rejects anything but a UUID (it goes into SQL)
    if args.print_sql:
        print(DUMP_SQL.replace("{game}", game), end="")
        return 0
    if args.from_json:
        dump = json.loads(args.from_json.read_text(encoding="utf-8"))
    elif args.database_url or os.environ.get("DATABASE_URL"):
        url = args.database_url or os.environ["DATABASE_URL"]
        dump = asyncio.run(fetch_dump(url, game))
    else:
        parser.error("DATABASE_URL, --database-url or --from-json is required")
    written = write_scenes(
        dump, game, args.out, force=args.force, genre=args.genre, language=args.language
    )
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
