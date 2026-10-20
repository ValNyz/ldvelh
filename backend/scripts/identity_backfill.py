"""Finish the identity migration of the games written before it (spec §5.2, #152).

The migration (db/migrations/20261020000001_entity_identity.sql, section 3) re-identifies
the registry, registers the companions, gives every entity the aliases of its names and
rewrites the journal, all without a word of any language. What reads a language is done
here, per game, in one transaction (`run`):
0. a game without language gets IdentityConfig.default_language;
1. identity_legacy_normalise (SQL, from the migration): alias and registry norms, orphans,
   normalised collisions (suffix), mentions rebuilt from narrator_context;
2. a game that had no language (written before the migration) gets its unknown
   characters classified (services/identity/classify.py, the rule the dry-run report
   prints), its journaled characters rows included;
3. the derived aliases (short forms, titles: services/identity/aliases.derive) of every
   entity, once (ON CONFLICT DO NOTHING);
4. the exceptions the user wrote after reading the report: {id: {true_name: …}} makes the
   character's true name that, {id: {descriptor: …}} makes it a descriptor.
Idempotent: a second run changes nothing. Run by backend/entrypoint.sh after `dbmate up`
(games that need it only: no language, or a norm missing); the startup check refuses to
serve while one does.

Usage (from backend/):
  DATABASE_URL=postgresql://… python -m scripts.identity_backfill [--game ID]
      [--exceptions FILE.yaml]   (or --database-url, visible in ps)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import yaml

# Kinds derive() adds to the forms the migration already gave.
DERIVED_KINDS = ("short", "title")
EXCEPTION_KEYS = ("true_name", "descriptor")

NEEDING_BACKFILL_SQL = """
SELECT gm.id FROM games AS gm
 WHERE gm.language IS NULL
    OR EXISTS (SELECT 1 FROM entity_registry AS er
                WHERE er.game_id = gm.id AND er.name_norm IS NULL)
    OR EXISTS (SELECT 1 FROM entity_aliases AS al
                WHERE al.game_id = gm.id AND al.alias_norm IS NULL)
 ORDER BY gm.created_at, gm.id"""


def _json(value) -> dict | None:
    """A jsonb value, whether the connection decodes jsonb or not."""
    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)


async def run(
    conn, game_id: UUID, exceptions: Mapping[UUID, Mapping[str, str]] | None = None
) -> dict[str, int]:
    """Backfill one game (steps 0-4 of the module docstring); the counts of each step."""
    async with conn.transaction():
        legacy = await conn.fetchval(
            "SELECT language IS NULL FROM games WHERE id = $1 FOR UPDATE", game_id
        )
        if legacy is None:
            raise LookupError(f"no game {game_id}")
        if legacy:
            from config import get_identity_config

            await conn.execute(
                "UPDATE games SET language = $2 WHERE id = $1 AND language IS NULL",
                game_id,
                get_identity_config().default_language,
            )
        counts = dict(
            _json(
                await conn.fetchval(
                    "SELECT identity_legacy_normalise($1)::text", game_id
                )
            )
        )
        normalizer, lexicon = await _packs(conn, game_id)
        if legacy:
            counts["journal_rows_classified"] = await _classify_journal(
                conn, game_id, normalizer, lexicon
            )
            counts["characters_reclassified"] = await _classify(
                conn, game_id, normalizer, lexicon
            )
        counts["derived_aliases"] = await _derive_aliases(
            conn, game_id, normalizer, lexicon
        )
        counts["exceptions"] = await _apply_exceptions(conn, game_id, exceptions or {})
    return counts


async def _packs(conn, game_id: UUID):
    from packs.loader import load_lang
    from repos.entities import game_language
    from services.identity.lexicon import for_game
    from services.identity.normalize import Normalizer

    language, genre = await game_language(conn, game_id)
    return Normalizer(load_lang(language)), for_game(language, genre)


async def legacy_characters(conn, game_id: UUID):
    """The characters of a game as the classification plan reads them, oldest first."""
    from services.identity.classify import LegacyCharacter

    rows = await conn.fetch(
        """SELECT ch.id, ch.true_name, ch.descriptor, ch.known_by_protagonist,
                  ch.label_suffix, er.name_norm
             FROM characters AS ch JOIN entity_registry AS er ON er.id = ch.id
            WHERE ch.game_id = $1
            ORDER BY ch.created_at, er.handle, ch.id""",
        game_id,
    )
    return [
        LegacyCharacter(
            id=r["id"],
            name=r["true_name"] or r["descriptor"],
            descriptor=r["descriptor"],
            settled=bool(r["known_by_protagonist"]) or r["true_name"] is None,
            label_suffix=r["label_suffix"],
            label_norm=r["name_norm"] or "",
        )
        for r in rows
    ]


async def _drop_true_name_aliases(conn, character_id: UUID) -> None:
    """The aliases the migration made of a name that turns out not to be a true name: the
    name itself and its derived forms (the descriptor keeps its own)."""
    await conn.execute(
        """DELETE FROM entity_aliases
            WHERE entity_id = $1 AND source = 'migration'
              AND kind IN ('true_name', 'short', 'title')""",
        character_id,
    )


async def _classify(conn, game_id: UUID, normalizer, lexicon) -> int:
    """Step 2: the unknown characters whose name is a descriptor lose their provisional
    true name (and its alias, made by the migration), take the descriptor and, when their
    new label normalises like another character's, a label suffix."""
    from services.identity.classify import plan_classification

    changed = 0
    plan = plan_classification(
        await legacy_characters(conn, game_id), normalizer, lexicon
    )
    for _, verdict, write in plan:
        if write is None:
            continue
        await _drop_true_name_aliases(conn, write.id)
        await conn.execute(
            """UPDATE characters SET true_name = NULL, descriptor = $2, label_suffix = $3
                WHERE id = $1""",
            write.id,
            verdict.descriptor,
            write.label_suffix,
        )
        if write.extra_descriptor:
            await conn.execute(
                """INSERT INTO entity_aliases
                          (game_id, entity_id, entity_type, alias, kind, known, source)
                   VALUES ($1, $2, 'character', $3, 'descriptor', true, 'migration')
                   ON CONFLICT DO NOTHING""",
                game_id,
                write.id,
                write.extra_descriptor,
            )
        changed += 1
    return changed


async def _classify_journal(conn, game_id: UUID, normalizer, lexicon) -> int:
    """Step 2 on the journal: a characters row of a turn played before the migration holds
    the provisional model (true_name = name); an unknown character's gets the verdict of
    its own name, so that undoing the turn restores the classified model. Runs before the
    live rows are classified: a row without descriptor takes the character's own."""
    live = {
        r["id"]: r
        for r in await conn.fetch(
            "SELECT id, descriptor, known_by_protagonist FROM characters WHERE game_id = $1",
            game_id,
        )
    }
    rows = await conn.fetch(
        """SELECT wc.id, wc.row_id, wc.old_row::text AS old_row, wc.new_row::text AS new_row
             FROM world_changes AS wc JOIN turns AS tn ON tn.id = wc.turn_id
            WHERE tn.game_id = $1 AND wc.table_name = 'characters'""",
        game_id,
    )
    changed = 0
    renames = set()
    for row in rows:
        character = live.get(row["row_id"])
        before = [_json(row["old_row"]), _json(row["new_row"])]
        sides = [_classified(side, character, normalizer, lexicon) for side in before]
        if sides != before:
            await conn.execute(
                "UPDATE world_changes SET old_row = $2::text::jsonb, new_row = $3::text::jsonb"
                " WHERE id = $1",
                row["id"],
                None if sides[0] is None else json.dumps(sides[0]),
                None if sides[1] is None else json.dumps(sides[1]),
            )
            renames |= {
                (row["row_id"], old["name"], new["name"])
                for old, new in zip(before, sides, strict=True)
                if old and new and old.get("name") != new.get("name")
            }
            changed += 1
    for row_id, old_name, new_name in renames:
        # The registry's journal rows of the same name follow (name and norm).
        for side in ("old_row", "new_row"):
            await conn.execute(
                f"""UPDATE world_changes AS wc
                       SET {side} = wc.{side} || jsonb_build_object(
                               'name', $3::text,
                               'name_norm', ldvelh_norm_for_game($4, $3::text))
                      FROM turns AS tn
                     WHERE tn.id = wc.turn_id AND tn.game_id = $4
                       AND wc.table_name = 'entity_registry' AND wc.row_id = $1
                       AND wc.{side} ->> 'name' = $2""",
                row_id,
                old_name,
                new_name,
                game_id,
            )
    return changed


def _classified(change: dict | None, character, normalizer, lexicon) -> dict | None:
    from services.identity.classify import classify_unknown_character

    if (
        not change
        or "true_name" not in change
        or change["true_name"] != change.get("name")
    ):
        return change
    known = change.get(
        "known_by_protagonist",
        character["known_by_protagonist"] if character else False,
    )
    if known or not change.get("name"):
        return change
    seen = change.get("descriptor", character["descriptor"] if character else None)
    verdict = classify_unknown_character(change["name"], seen, normalizer, lexicon)
    if verdict.kind == "true_name":
        return change
    return {
        **change,
        "true_name": None,
        "descriptor": verdict.descriptor,
        "name": verdict.descriptor,
    }


async def _derive_aliases(conn, game_id: UUID, normalizer, lexicon) -> int:
    """Step 3: the short forms and titles of every live entity's names (aliases.derive);
    a form already there (same norm) is kept as it is."""
    from services.identity.aliases import derive

    entities = await conn.fetch(
        """SELECT er.id, er.entity_type, er.name, ch.true_name,
                  COALESCE(ch.known_by_protagonist, false) AS known,
                  COALESCE((SELECT bool_or(al.secret) FROM entity_aliases AS al
                             WHERE al.entity_id = er.id AND al.kind = 'true_name'), false)
                      AS secret
             FROM entity_registry AS er LEFT JOIN characters AS ch ON ch.id = er.id
            WHERE er.game_id = $1 AND er.merged_into IS NULL
            ORDER BY er.handle""",
        game_id,
    )
    rows = []
    for entity in entities:
        if entity["entity_type"] == "character":
            if not entity["true_name"]:
                continue
            specs = derive(
                entity["true_name"],
                kind="true_name",
                known=entity["known"],
                secret=entity["secret"],
                normalizer=normalizer,
                lexicon=lexicon,
            )
        else:
            specs = derive(
                entity["name"],
                kind="label",
                known=True,
                normalizer=normalizer,
                lexicon=lexicon,
            )
        rows += [
            (
                game_id,
                entity["id"],
                entity["entity_type"],
                s.text,
                s.kind,
                s.known,
                s.secret,
            )
            for s in specs
            if s.kind in DERIVED_KINDS
        ]
    if not rows:
        return 0
    count = "SELECT count(*) FROM entity_aliases WHERE game_id = $1"
    before = await conn.fetchval(count, game_id)
    await conn.executemany(
        """INSERT INTO entity_aliases
                  (game_id, entity_id, entity_type, alias, kind, known, secret, source)
           VALUES ($1, $2, $3, $4, $5, $6, $7, 'migration')
           ON CONFLICT DO NOTHING""",
        rows,
    )
    return await conn.fetchval(count, game_id) - before


async def _apply_exceptions(
    conn, game_id: UUID, exceptions: Mapping[UUID, Mapping[str, str]]
) -> int:
    """Step 4: the user's corrections of the classification, for the characters of this
    game (an id of another game is left to that game's run)."""
    applied = 0
    for character_id, correction in exceptions.items():
        exists = await conn.fetchval(
            "SELECT 1 FROM characters WHERE id = $1 AND game_id = $2",
            character_id,
            game_id,
        )
        if not exists:
            continue
        if "true_name" in correction:
            status = await conn.execute(
                """UPDATE characters SET true_name = $2
                    WHERE id = $1 AND true_name IS DISTINCT FROM $2""",
                character_id,
                correction["true_name"],
            )
        else:
            await _drop_true_name_aliases(conn, character_id)
            status = await conn.execute(
                """UPDATE characters SET true_name = NULL, descriptor = $2
                    WHERE id = $1 AND (true_name IS NOT NULL
                                       OR descriptor IS DISTINCT FROM $2)""",
                character_id,
                correction["descriptor"],
            )
        applied += status != "UPDATE 0"
    return applied


def load_exceptions(path: Path) -> dict[UUID, dict[str, str]]:
    """The exceptions file: {character id: {true_name: …} | {descriptor: …}}."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"{path}: a mapping of character ids is expected")
    exceptions = {}
    for key, correction in raw.items():
        if (
            not isinstance(correction, dict)
            or len(correction) != 1
            or next(iter(correction)) not in EXCEPTION_KEYS
            or not str(next(iter(correction.values())) or "").strip()
        ):
            raise ValueError(
                f"{path}: {key}: one of {', '.join(EXCEPTION_KEYS)} with a non-empty value"
            )
        exceptions[UUID(str(key))] = {k: str(v).strip() for k, v in correction.items()}
    return exceptions


async def _main(args: argparse.Namespace) -> int:
    import asyncpg

    exceptions = load_exceptions(args.exceptions) if args.exceptions else {}
    conn = await asyncpg.connect(args.database_url)
    try:
        if args.game:
            games = [args.game]
        else:
            games = [r["id"] for r in await conn.fetch(NEEDING_BACKFILL_SQL)]
            if exceptions:
                games += [
                    r["game_id"]
                    for r in await conn.fetch(
                        "SELECT DISTINCT game_id FROM characters WHERE id = ANY($1::uuid[])",
                        list(exceptions),
                    )
                    if r["game_id"] not in games
                ]
        for game_id in games:
            counts = await run(conn, game_id, exceptions)
            print(
                f"[IDENTITY_BACKFILL] game={game_id} {json.dumps(counts, sort_keys=True)}"
            )
        print(f"[IDENTITY_BACKFILL] {len(games)} game(s) backfilled")
    finally:
        await conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--game", type=UUID, help="only this game")
    parser.add_argument(
        "--exceptions", type=Path, help="YAML corrections of the report"
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
