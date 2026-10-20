"""Finish the identity migration of the games written before it (spec §5.2, #152).

The migration (db/migrations/20261020000001_entity_identity.sql, section 3) re-identifies
the registry, registers the companions, gives every entity the aliases of its names and
rewrites the journal, all without a word of any language. What reads a language is done
here, per game, in one transaction (`run`):
0. a game without language gets IdentityConfig.default_language;
1. identity_legacy_normalise (SQL, from the migration): alias and registry norms, orphans,
   normalised collisions (suffix), mentions rebuilt from narrator_context;
2. a legacy game (see `is_legacy`) gets its unknown characters classified
   (services/identity/classify.py, the rule the dry-run report prints), its journaled
   characters rows included (scripts/identity_journal.py);
3. the exceptions the user wrote after reading the report (scripts/identity_exceptions.py);
4. the derived aliases (short forms, titles: services/identity/aliases.derive) of every
   entity, once (ON CONFLICT DO NOTHING), corrected names included.
An `identity_events` row ('identity_backfill') marks every game a run touched as done
(durable state, see identity_event_is_state in the migration). Idempotent: a second
run changes nothing. Run by backend/entrypoint.sh after `dbmate up`, with the exceptions
of IDENTITY_BACKFILL_EXCEPTIONS (games that need it only); the startup check refuses to
serve while one does. CONTRIBUTING, "Deploying the identity migration", has the procedure.

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

# Kinds derive() adds to the forms the migration already gave.
DERIVED_KINDS = ("short", "title")
DONE_EVENT = "identity_backfill"

# A legacy game: written before the migration (its aliases come from section 3, source
# 'migration') and not backfilled yet. A game created since has neither: its names come
# from the triggers ('system'), whatever its language.
LEGACY_SQL = """
SELECT NOT EXISTS (SELECT 1 FROM identity_events
                    WHERE game_id = $1 AND kind = 'identity_backfill')
       AND EXISTS (SELECT 1 FROM entity_aliases
                    WHERE game_id = $1 AND source = 'migration')"""

NEEDING_BACKFILL_SQL = """
SELECT gm.id FROM games AS gm
 WHERE gm.language IS NULL
    OR EXISTS (SELECT 1 FROM entity_registry AS er
                WHERE er.game_id = gm.id AND er.name_norm IS NULL)
    OR EXISTS (SELECT 1 FROM entity_aliases AS al
                WHERE al.game_id = gm.id AND al.alias_norm IS NULL)
    OR (NOT EXISTS (SELECT 1 FROM identity_events AS ev
                     WHERE ev.game_id = gm.id AND ev.kind = 'identity_backfill')
        AND EXISTS (SELECT 1 FROM entity_aliases AS al
                     WHERE al.game_id = gm.id AND al.source = 'migration'))
 ORDER BY gm.created_at, gm.id"""


def _json(value) -> dict | None:
    """A jsonb value, whether the connection decodes jsonb or not."""
    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)


async def is_legacy(conn, game_id: UUID) -> bool:
    return bool(await conn.fetchval(LEGACY_SQL, game_id))


async def run(
    conn, game_id: UUID, exceptions: Mapping[UUID, Mapping[str, str]] | None = None
) -> dict[str, int]:
    """Backfill one game (steps 0-4 of the module docstring); the counts of each step."""
    from scripts.identity_exceptions import apply_exceptions
    from scripts.identity_journal import classify_journal

    async with conn.transaction():
        language = await conn.fetchrow(
            "SELECT language FROM games WHERE id = $1 FOR UPDATE", game_id
        )
        if language is None:
            raise LookupError(f"no game {game_id}")
        if language["language"] is None:
            from config import get_identity_config

            await conn.execute(
                "UPDATE games SET language = $2 WHERE id = $1",
                game_id,
                get_identity_config().default_language,
            )
        legacy = await is_legacy(conn, game_id)
        counts = dict(
            _json(
                await conn.fetchval(
                    "SELECT identity_legacy_normalise($1)::text", game_id
                )
            )
        )
        normalizer, lexicon = await _packs(conn, game_id)
        if legacy:
            counts["journal_rows_classified"] = await classify_journal(
                conn, game_id, normalizer, lexicon
            )
            counts["characters_reclassified"] = await _classify(
                conn, game_id, normalizer, lexicon
            )
        counts["exceptions"], skipped = await apply_exceptions(
            conn, game_id, exceptions or {}, normalizer
        )
        counts["exceptions_skipped"] = len(skipped)
        for character_id in skipped:
            print(
                f"[IDENTITY_BACKFILL] game={game_id} exception skipped for {character_id}:"
                " the player knows another true name since"
            )
        counts["derived_aliases"] = await _derive_aliases(
            conn, game_id, normalizer, lexicon
        )
        # The live aliases added above may clash with the alias rows of the journal.
        counts["journal_alias_conflicts"] = await conn.fetchval(
            "SELECT identity_journal_alias_conflicts($1)", game_id
        )
        # Every game the backfill touched is done, legacy or not: never classified again.
        await conn.execute(
            """INSERT INTO identity_events (game_id, kind, payload)
               SELECT $1, $2, $3::text::jsonb
                WHERE NOT EXISTS (SELECT 1 FROM identity_events
                                   WHERE game_id = $1 AND kind = $2)""",
            game_id,
            DONE_EVENT,
            json.dumps(counts, sort_keys=True),
        )
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


async def _classify(conn, game_id: UUID, normalizer, lexicon) -> int:
    """Step 2: the unknown characters whose name is a descriptor lose their provisional
    true name (and its alias, made by the migration), take the descriptor and, when their
    new label normalises like another character's, a label suffix."""
    from scripts.identity_exceptions import drop_true_name_aliases
    from services.identity.classify import plan_classification

    changed = 0
    plan = plan_classification(
        await legacy_characters(conn, game_id), normalizer, lexicon
    )
    for _, verdict, write in plan:
        if write is None:
            continue
        await drop_true_name_aliases(conn, write.id)
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


async def _main(args: argparse.Namespace) -> int:
    import asyncpg

    from scripts.identity_exceptions import load_exceptions

    exceptions = load_exceptions(args.exceptions) if args.exceptions else {}
    conn = await asyncpg.connect(args.database_url)
    try:
        if args.game:
            games = [args.game]
        else:
            games = [r["id"] for r in await conn.fetch(NEEDING_BACKFILL_SQL)]
            if exceptions:  # games with a correction not applied yet
                games += [
                    r["game_id"]
                    for r in await conn.fetch(
                        """SELECT DISTINCT ch.game_id
                             FROM unnest($1::uuid[], $2::text[]) AS ex (id, payload)
                             JOIN characters AS ch ON ch.id = ex.id
                            WHERE NOT EXISTS (
                                SELECT 1 FROM identity_events AS ev
                                 WHERE ev.entity_id = ch.id
                                   AND ev.kind = 'identity_exception'
                                   AND ev.payload = ex.payload::jsonb)""",
                        list(exceptions),
                        [json.dumps(c, sort_keys=True) for c in exceptions.values()],
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
        "--exceptions",
        type=Path,
        default=os.environ.get("IDENTITY_BACKFILL_EXCEPTIONS") or None,
        help="YAML corrections of the report (default: $IDENTITY_BACKFILL_EXCEPTIONS)",
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
