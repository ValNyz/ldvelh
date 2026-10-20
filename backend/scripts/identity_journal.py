"""The journal of the turns played before the identity migration, kept in step with the
name model the backfill gives the characters (spec §5.2, #152, review I7, I3).

Section 3.3 of the migration rewrote those rows to the new column set with the provisional
model (true_name = the old name). When the backfill classifies a character, or applies a
user exception, the rows that describe it must say the same, so that undoing such a turn
after the deploy restores the model in force, not the provisional one: its characters
rows, its registry rows (name and norm) and, for a character the turn deleted, the alias
rows 3.3 added (identity_journal_aliases).
"""

from __future__ import annotations

import json
from uuid import UUID


def _json(value) -> dict | None:
    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)


def _dump(value: dict | None) -> str | None:
    return None if value is None else json.dumps(value)


async def _character_rows(conn, game_id: UUID, row_id: UUID | None = None):
    """The characters rows of the turns played before the migration: those created before
    the game's first backfill; during that run, all of them for a legacy game (aliases
    from the migration) and none for a game created since (all its turns came after)."""
    return await conn.fetch(
        """SELECT wc.id, wc.turn_id, wc.op, wc.row_id, wc.old_row::text AS old_row,
                  wc.new_row::text AS new_row
             FROM world_changes AS wc JOIN turns AS tn ON tn.id = wc.turn_id
            WHERE tn.game_id = $1 AND wc.table_name = 'characters'
              AND ($2::uuid IS NULL OR wc.row_id = $2)
              AND tn.created_at < COALESCE(
                      (SELECT min(ev.created_at) FROM identity_events AS ev
                        WHERE ev.game_id = $1 AND ev.kind = 'identity_backfill'),
                      CASE WHEN EXISTS (SELECT 1 FROM entity_aliases AS al
                                         WHERE al.game_id = $1 AND al.source = 'migration')
                           THEN 'infinity'::timestamptz
                           ELSE '-infinity'::timestamptz END)
            ORDER BY wc.id""",
        game_id,
        row_id,
    )


async def _rewrite(conn, game_id: UUID, row, before: list, after: list) -> None:
    """Store a characters row's new sides; the registry rows of the same name and, for a
    character the turn deleted (no live row), its alias rows follow."""
    await conn.execute(
        "UPDATE world_changes SET old_row = $2::text::jsonb, new_row = $3::text::jsonb"
        " WHERE id = $1",
        row["id"],
        _dump(after[0]),
        _dump(after[1]),
    )
    for old, new in zip(before, after, strict=True):
        if old and new and old.get("name") != new.get("name"):
            await _registry_rows_follow(
                conn, game_id, row["row_id"], old["name"], new["name"]
            )
    gone = not await conn.fetchval(
        "SELECT 1 FROM characters WHERE id = $1", row["row_id"]
    )
    for old, new in zip(before, after, strict=True):
        if (
            not gone
            and old
            and new
            and new.get("true_name") is None
            and old.get("name")
        ):
            # A former name the classification reads as a descriptor: its alias row (the
            # rename case of 3.3) is a seen descriptor, neither a true name nor a secret.
            await conn.execute(
                """UPDATE world_changes
                      SET old_row = old_row || '{"kind": "descriptor", "known": true,
                                                  "secret": false}'::jsonb
                    WHERE turn_id = $1 AND table_name = 'entity_aliases'
                      AND old_row ->> 'entity_id' = $2::uuid::text
                      AND old_row ->> 'source' = 'migration'
                      AND old_row ->> 'kind' = 'true_name'
                      AND old_row ->> 'alias' = $3""",
                row["turn_id"],
                row["row_id"],
                old["name"],
            )
    if row["op"] == "D" and gone:
        await conn.execute(
            """DELETE FROM world_changes
                WHERE turn_id = $1 AND table_name = 'entity_aliases'
                  AND old_row ->> 'entity_id' = $2::uuid::text
                  AND old_row ->> 'source' = 'migration'""",
            row["turn_id"],
            row["row_id"],
        )
        await conn.execute(
            "SELECT identity_journal_aliases($1, 'character', $2::text::jsonb)",
            row["turn_id"],
            _dump(after[0]),
        )


async def _registry_rows_follow(
    conn, game_id: UUID, row_id: UUID, old_name: str, new_name: str
) -> None:
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


async def classify_journal(conn, game_id: UUID, normalizer, lexicon) -> int:
    """A characters row of an unknown character holding the provisional model takes the
    verdict of its own name (classify_unknown_character). Runs before the live rows are
    classified: a row without descriptor takes the character's own. Returns the rows
    rewritten."""
    live = {
        r["id"]: r
        for r in await conn.fetch(
            "SELECT id, descriptor, known_by_protagonist FROM characters WHERE game_id = $1",
            game_id,
        )
    }
    changed = 0
    for row in await _character_rows(conn, game_id):
        character = live.get(row["row_id"])
        before = [_json(row["old_row"]), _json(row["new_row"])]
        after = [_classified(side, character, normalizer, lexicon) for side in before]
        if after != before:
            await _rewrite(conn, game_id, row, before, after)
            changed += 1
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


MODEL_KEYS = ("true_name", "descriptor", "label_suffix", "name")


async def follow_model(
    conn, game_id: UUID, row_id: UUID, before: dict, after: dict
) -> int:
    """A character's name model changed from `before` to `after` (the MODEL_KEYS of its
    live row): its journal rows that held `before` (same name) now hold `after`."""
    changed = 0
    for row in await _character_rows(conn, game_id, row_id):
        sides = [_json(row["old_row"]), _json(row["new_row"])]
        moved = [
            {**side, **{k: after[k] for k in MODEL_KEYS}}
            if side and side.get("name") == before["name"]
            else side
            for side in sides
        ]
        if moved != sides:
            await _rewrite(conn, game_id, row, sides, moved)
            changed += 1
    # A former name the classification had read as a descriptor and that is now the true
    # name needs no way back here: its journal alias row normalises like the live true
    # name alias the trigger has just made, so identity_journal_alias_conflicts drops it
    # (the backfill runs it last) and an undo leaves that true name unknown.
    return changed
