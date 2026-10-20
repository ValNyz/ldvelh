"""The user's corrections of the dry-run report's classification (spec §5.2 step 3, #152).

A YAML file `{character id: {true_name: …} | {descriptor: …}}`, read by the backfill
(`--exceptions`, or IDENTITY_BACKFILL_EXCEPTIONS at deploy). A correction follows the
rules of the classification itself:
- `true_name: X` makes X the character's true name. The known descriptor alias of that
  form goes first (a true name the PC does not know is not known); a descriptor whose
  normalised words contain X's goes with its alias (the classification's copy of a name
  with no seen descriptor, and a seen descriptor that names X too), so the player reads
  the pack's unknown label, never the hidden name (the CHECK holds: the true name is set);
  the true name's alias is secret when the character is mandatory and unknown (§5.2 step 4).
- `descriptor: Y` makes Y the descriptor and drops the true name and its forms.
- the new label takes a homonym suffix when another character already holds it (R9);
- the journal of the turns played before the migration follows (identity_journal).
Each correction is applied once: an `identity_events` row ('identity_exception', with the
correction; durable state) records it, so a later boot never undoes what the game did
since. A correction that arrives after play is skipped (and reported) when the player
knows the character under another true name: it would overwrite a reveal. Only the
journal of turns played before the migration follows a correction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import yaml

EXCEPTION_KEYS = ("true_name", "descriptor")
EVENT_KIND = "identity_exception"


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


async def drop_true_name_aliases(conn, character_id: UUID) -> None:
    """The aliases the migration made of a name that turns out not to be a true name: the
    name itself and its derived forms (the descriptor keeps its own)."""
    await conn.execute(
        """DELETE FROM entity_aliases
            WHERE entity_id = $1 AND source = 'migration'
              AND kind IN ('true_name', 'short', 'title')""",
        character_id,
    )


def names_within(normalizer, true_name: str, descriptor: str) -> bool:
    """The descriptor spells the true name: its normalised words hold the true name's."""
    return f" {normalizer.norm(true_name)} " in f" {normalizer.norm(descriptor)} "


async def _model(conn, character_id: UUID) -> dict:
    row = await conn.fetchrow(
        "SELECT true_name, descriptor, label_suffix, name FROM characters WHERE id = $1",
        character_id,
    )
    return dict(row)


async def _suffix(conn, game_id: UUID, character_id: UUID, base: str, normalizer):
    """The homonym suffix the label `base` needs among the game's other characters."""
    from services.identity.classify import free_suffix

    taken: dict[str, set[UUID]] = {}
    for row in await conn.fetch(
        """SELECT er.id, er.name_norm FROM entity_registry AS er
            WHERE er.game_id = $1 AND er.entity_type = 'character'
              AND er.merged_into IS NULL AND er.id <> $2""",
        game_id,
        character_id,
    ):
        taken.setdefault(row["name_norm"], set()).add(row["id"])
    return free_suffix(base, None, taken, normalizer)


async def apply_exceptions(
    conn, game_id: UUID, exceptions: Mapping[UUID, Mapping[str, str]], normalizer
) -> tuple[list[UUID], list[UUID]]:
    """The corrections for the characters of this game not applied yet: (the characters
    corrected, the characters skipped because the player knows another true name). An id
    of another game is left to that game's run."""
    from scripts.identity_journal import follow_model

    applied, skipped = [], []
    for character_id, correction in exceptions.items():
        payload = json.dumps(dict(correction), sort_keys=True)
        pending = await conn.fetchval(
            """SELECT NOT EXISTS (SELECT 1 FROM identity_events
                                   WHERE entity_id = $1 AND kind = $3
                                     AND payload = $4::text::jsonb)
                 FROM characters WHERE id = $1 AND game_id = $2""",
            character_id,
            game_id,
            EVENT_KIND,
            payload,
        )
        if not pending:
            continue
        before = await _model(conn, character_id)
        revealed = await conn.fetchval(
            "SELECT known_by_protagonist FROM characters WHERE id = $1", character_id
        )
        if revealed and before["true_name"] != correction.get("true_name"):
            skipped.append(character_id)
            continue
        if "true_name" in correction:
            name = correction["true_name"]
            descriptor = before["descriptor"]
            if descriptor and names_within(normalizer, name, descriptor):
                descriptor = None
            # Neither the true name nor a descriptor that spells it stays a known form.
            await conn.execute(
                """DELETE FROM entity_aliases
                    WHERE entity_id = $1 AND kind = 'descriptor'
                      AND alias_norm IN (ldvelh_norm_for_game(game_id, $2),
                                         ldvelh_norm_for_game(game_id, $3))""",
                character_id,
                name,
                before["descriptor"] if descriptor is None else name,
            )
            await conn.execute(
                """UPDATE characters SET true_name = $2, descriptor = $3, label_suffix = $4
                    WHERE id = $1""",
                character_id,
                name,
                descriptor,
                await _suffix(conn, game_id, character_id, name, normalizer),
            )
            await conn.execute(
                """UPDATE entity_aliases AS al
                      SET secret = ch.is_mandatory AND NOT ch.known_by_protagonist
                     FROM characters AS ch
                    WHERE ch.id = al.entity_id AND al.entity_id = $1
                      AND al.kind = 'true_name'
                      AND al.alias_norm = ldvelh_norm_for_game(ch.game_id, $2)""",
                character_id,
                name,
            )
        else:
            descriptor = correction["descriptor"]
            await drop_true_name_aliases(conn, character_id)
            await conn.execute(
                """UPDATE characters SET true_name = NULL, descriptor = $2, label_suffix = $3
                    WHERE id = $1""",
                character_id,
                descriptor,
                await _suffix(conn, game_id, character_id, descriptor, normalizer),
            )
        await follow_model(
            conn, game_id, character_id, before, await _model(conn, character_id)
        )
        await conn.execute(
            """INSERT INTO identity_events (game_id, kind, entity_id, payload)
               VALUES ($1, $2, $3, $4::text::jsonb)""",
            game_id,
            EVENT_KIND,
            character_id,
            payload,
        )
        applied.append(character_id)
    return applied, skipped
