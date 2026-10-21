"""Entity identity repository: references, registry rows, aliases, mentions and events.

Every lookup of an entity by a reference goes through the SQL `find_entity`, which needs
the entity type: a handle `E<n>`, an id, PROTAGONIST/COMPANION, else the normalised
labels and aliases of that type. Two matches or more give None (ambiguous), never an
arbitrary pick (spec §4.2). No function opens a connection or a transaction.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import NamedTuple
from uuid import UUID

from domain.identity import MentionRow

logger = logging.getLogger(__name__)

# Types an untyped reference (a fact participant, a relation end) may name. No order: a
# reference two types know (homonyms of two types, spec §4.10) is ambiguous, like one two
# entities of a type share (§4.2): None, never a pick.
ANY_ENTITY_TYPES: tuple[str, ...] = (
    "protagonist",
    "companion",
    "character",
    "organization",
    "location",
    "object",
)


@dataclass(frozen=True)
class RegistryRow:
    id: UUID
    entity_type: str
    name: str
    handle: int
    merged_into: UUID | None


@dataclass(frozen=True)
class AliasRow:
    id: UUID
    entity_id: UUID
    entity_type: str
    alias: str
    alias_norm: str
    kind: str
    known: bool
    secret: bool
    source: str
    turn_id: UUID | None


@dataclass(frozen=True)
class SuffixChange:
    """A label suffix to write with a rename: `suffix` (None clears it) and where it comes
    from (`origin`: scene_location or counter, for the label_suffixed event)."""

    suffix: str | None
    origin: str | None


@dataclass(frozen=True)
class UpsertTarget:
    """The live entity a write by name lands on (None: a new one), and whether the name
    was ambiguous (then nothing must be created under it).

    `by_label`: the entity holds the name as its label. `contested`: it was picked only as
    the holder of the label while the name is also another entity's alias (find_entity
    returned NULL); a caller that would rewrite the entity's data or delete another must
    not trust it."""

    entity_id: UUID | None
    by_label: bool
    ambiguous: bool
    contested: bool = False


async def find_entity(
    conn, game_id: UUID, ref: str | None, entity_type: str
) -> UUID | None:
    """The entity of `entity_type` that `ref` names, or None (unknown or ambiguous)."""
    if not entity_type:
        raise ValueError("find_entity needs an entity type")
    if ref is None or not ref.strip():
        return None
    return await conn.fetchval(
        "SELECT find_entity($1, $2, $3)", game_id, ref, str(entity_type)
    )


# References unique by construction: find_entity resolves them for one type at most.
_RESERVED_REF = re.compile(
    r"^(protagonist|companion|e[0-9]{1,9}"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


async def find_any(
    conn,
    game_id: UUID,
    ref: str | None,
    types: tuple[str, ...] = ANY_ENTITY_TYPES,
    *,
    live_first: bool = False,
) -> tuple[UUID, str] | None:
    """(id, type) of an untyped reference, only when exactly one type of `types` knows it
    and knows it once. A reference that two types know, or that two entities of one type
    share (labels and aliases together, as find_entity), is ambiguous: None, so an
    ambiguity among characters never falls through to a location of the same name. With
    `live_first`, a name is first looked up among the live entities (not removed from the
    world): a live entity is found even when a removed homonym shares its name, two live
    ones are an ambiguity, and only a name no live entity holds may name a removed one.
    The outcome is logged at INFO with counts only (the reference is story text)."""
    if ref is None or not ref.strip():
        return None
    if live_first and not _RESERVED_REF.match(ref.strip()):
        live = await candidate_counts(conn, game_id, ref, types, live_only=True)
        if len(live) == 1 and next(iter(live.values())) == 1:
            [entity_type] = live
            [entity_id] = await live_candidates(conn, game_id, ref, entity_type)
            return entity_id, entity_type
        if live:
            logger.info(
                f"[IDENTITY] untyped reference unresolved (types={len(live)},"
                f" live candidates={sum(live.values())})"
            )
            return None
    if _RESERVED_REF.match(ref.strip()):
        rows = await conn.fetch(
            """SELECT t.entity_type, find_entity($1, $2, t.entity_type) AS id
                 FROM unnest($3::text[]) AS t (entity_type)""",
            game_id,
            ref,
            list(types),
        )
        hits = [(r["id"], r["entity_type"]) for r in rows if r["id"] is not None]
        return hits[0] if len(hits) == 1 else None
    counts = await candidate_counts(conn, game_id, ref, types)
    if len(counts) == 1 and next(iter(counts.values())) == 1:
        [entity_type] = counts
        entity_id = await find_entity(conn, game_id, ref, entity_type)
        if entity_id is not None:
            return entity_id, entity_type
    logger.info(
        f"[IDENTITY] untyped reference unresolved (types={len(counts)},"
        f" candidates={sum(counts.values())})"
    )
    return None


async def candidate_counts(
    conn, game_id: UUID, ref: str, types: tuple[str, ...], *, live_only: bool = False
) -> dict[str, int]:
    """Entities of each type of `types` (merges followed; with `live_only`, those not
    removed from the world only) whose label or alias has the normalised form of `ref`:
    find_entity's last step, counted (2 or more: ambiguous)."""
    rows = await conn.fetch(
        """WITH ref AS (SELECT ldvelh_norm_for_game($1, $2) AS norm),
                candidates AS (
                    SELECT er.entity_type, entity_follow_merge(er.id) AS id
                      FROM entity_registry AS er, ref
                     WHERE er.game_id = $1 AND er.entity_type = ANY($3::text[])
                       AND er.name_norm = ref.norm
                    UNION
                    SELECT al.entity_type, entity_follow_merge(al.entity_id)
                      FROM entity_aliases AS al, ref
                     WHERE al.game_id = $1 AND al.entity_type = ANY($3::text[])
                       AND al.alias_norm = ref.norm)
           SELECT entity_type, count(DISTINCT id) AS candidates
             FROM candidates
            WHERE NOT $4
               OR (identity_domain_row(entity_type, id) IS NOT NULL
                   AND (identity_domain_row(entity_type, id) ->> 'removed_cycle') IS NULL)
            GROUP BY entity_type""",
        game_id,
        ref,
        list(types),
        live_only,
    )
    return {r["entity_type"]: r["candidates"] for r in rows}


async def find_for_upsert(
    conn, game_id: UUID, name: str, entity_type: str
) -> UpsertTarget:
    """Where a create-or-update by `name` lands: the entity find_entity resolves (by its
    label, or by an alias), else the live entity whose label has the same normalised form
    (the old UNIQUE (game_id, name) target, when an alias elsewhere makes the name
    ambiguous); `ambiguous` when only aliases of several entities match it."""
    row = await conn.fetchrow(
        """WITH ref AS (SELECT ldvelh_norm_for_game($1, $2) AS norm)
           SELECT find_entity($1, $2, $3) AS found,
                  (SELECT er.id FROM entity_registry AS er, ref
                    WHERE er.game_id = $1 AND er.entity_type = $3
                      AND er.merged_into IS NULL AND er.name_norm = ref.norm) AS owner,
                  EXISTS (SELECT 1 FROM entity_aliases AS al, ref
                           WHERE al.game_id = $1 AND al.entity_type = $3
                             AND al.alias_norm = ref.norm) AS aliased""",
        game_id,
        name,
        str(entity_type),
    )
    if row["found"] is not None:
        return UpsertTarget(row["found"], row["found"] == row["owner"], False)
    if row["owner"] is not None:
        logger.info("[IDENTITY] ambiguous name, the entity holding it as label is used")
        return UpsertTarget(row["owner"], True, False, contested=True)
    if row["aliased"]:
        logger.info("[IDENTITY] ambiguous name, nothing created under it")
        return UpsertTarget(None, False, True)
    return UpsertTarget(None, False, False)


async def get_registry(conn, game_id: UUID, entity_id: UUID) -> RegistryRow | None:
    row = await conn.fetchrow(
        """SELECT id, entity_type, name, handle, merged_into FROM entity_registry
           WHERE game_id = $1 AND id = $2""",
        game_id,
        entity_id,
    )
    return RegistryRow(**dict(row)) if row else None


async def live_entity_count(conn, game_id: UUID) -> int:
    """Entities of the game in the registry (merge tombstones left out)."""
    return await conn.fetchval(
        "SELECT count(*) FROM entity_registry WHERE game_id = $1 AND merged_into IS NULL",
        game_id,
    )


async def follow_merge(conn, entity_id: UUID) -> UUID:
    """The live entity behind `entity_id` (merge tombstones followed)."""
    return await conn.fetchval("SELECT entity_follow_merge($1)", entity_id)


async def follow_merges(conn, entity_ids: list[UUID]) -> dict[UUID, UUID]:
    """The live entity behind each merge tombstone of `entity_ids` (live ids left out)."""
    rows = await conn.fetch(
        """SELECT id, entity_follow_merge(id) AS live
             FROM unnest($1::uuid[]) AS ids(id)""",
        list(entity_ids),
    )
    return {r["id"]: r["live"] for r in rows if r["live"] != r["id"]}


async def insert_alias(
    conn,
    game_id: UUID,
    entity_id: UUID,
    entity_type: str,
    alias: str,
    kind: str,
    *,
    known: bool,
    secret: bool = False,
    source: str,
    turn_id: UUID | None = None,
    evidence: str | None = None,
) -> bool:
    """Add an alias; False when the entity already has one of the same normalised form."""
    inserted = await conn.fetchval(
        """INSERT INTO entity_aliases (game_id, entity_id, entity_type, alias, kind, known,
                                       secret, source, turn_id, evidence)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
           ON CONFLICT (game_id, entity_id, alias_norm) DO NOTHING
           RETURNING id""",
        game_id,
        entity_id,
        str(entity_type),
        alias,
        kind,
        known,
        secret,
        source,
        turn_id,
        evidence,
    )
    return inserted is not None


async def list_aliases(conn, game_id: UUID, entity_id: UUID) -> list[AliasRow]:
    rows = await conn.fetch(
        """SELECT id, entity_id, entity_type, alias, alias_norm, kind, known, secret, source,
                  turn_id
           FROM entity_aliases WHERE game_id = $1 AND entity_id = $2
           ORDER BY created_at, alias_norm""",
        game_id,
        entity_id,
    )
    return [AliasRow(**dict(r)) for r in rows]


async def insert_mentions(
    conn,
    game_id: UUID,
    message_id: UUID,
    turn_id: UUID | None,
    mentions: list[MentionRow],
) -> int:
    """Store the resolved spans of a message; a span already stored is kept. Returns the
    number of rows written."""
    written = 0
    for m in mentions:
        inserted = await conn.fetchval(
            """INSERT INTO entity_mentions (game_id, message_id, turn_id, start_pos, end_pos,
                                            surface, entity_id, decision, evidence)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               ON CONFLICT (message_id, start_pos, end_pos) DO NOTHING
               RETURNING id""",
            game_id,
            message_id,
            turn_id,
            m.start_pos,
            m.end_pos,
            m.surface,
            m.entity_id,
            m.decision,
            m.evidence,
        )
        written += inserted is not None
    return written


async def mentions_for_messages(
    conn, game_id: UUID, message_ids: list[UUID], *, disclosed: list[UUID] = ()
) -> dict[UUID, list[MentionRow]]:
    """Spans of each message, in text order, on the live entity (merges followed), with
    the name the player may read as label: never a secret name (spec §4.8; `disclosed`:
    the entities an open disclosure lets through), None when nothing is readable."""
    if not message_ids:
        return {}
    rows = await conn.fetch(
        f"""SELECT m.message_id, m.start_pos, m.end_pos, m.surface, m.decision,
                  m.evidence, live.id AS entity_id, er.entity_type,
                  {_READABLE_LABEL.format(id="live.id")} AS label
           FROM entity_mentions AS m
           CROSS JOIN LATERAL (SELECT entity_follow_merge(m.entity_id) AS id) AS live
           JOIN entity_registry AS er ON er.id = live.id
           WHERE m.game_id = $1 AND m.message_id = ANY($2::uuid[])
           ORDER BY m.message_id, m.start_pos, m.end_pos""",
        game_id,
        list(message_ids),
        list(disclosed),
    )
    result: dict[UUID, list[MentionRow]] = {}
    for r in rows:
        values = dict(r)
        message_id = values.pop("message_id")
        result.setdefault(message_id, []).append(MentionRow(**values))
    return result


async def insert_event(
    conn,
    game_id: UUID,
    kind: str,
    *,
    turn_id: UUID | None = None,
    entity_id: UUID | None = None,
    payload: dict,
) -> None:
    """Identity telemetry (not journaled: a rollback keeps it, like llm_calls)."""
    await conn.execute(
        """INSERT INTO identity_events (game_id, turn_id, kind, entity_id, payload)
           VALUES ($1, $2, $3, $4, $5::jsonb)""",
        game_id,
        turn_id,
        kind,
        entity_id,
        payload,
    )


async def display_for_player(conn, entity_id: UUID) -> str:
    """What the player may read for the entity (never an unknown character's true name)."""
    return await conn.fetchval("SELECT display_for_player($1)", entity_id)


async def handle_of(conn, entity_id: UUID) -> int | None:
    return await conn.fetchval(
        "SELECT handle FROM entity_registry WHERE id = $1", entity_id
    )


async def entity_by_handle(conn, game_id: UUID, handle: int) -> UUID | None:
    return await conn.fetchval(
        "SELECT id FROM entity_registry WHERE game_id = $1 AND handle = $2",
        game_id,
        handle,
    )


async def game_language(conn, game_id: UUID) -> tuple[str | None, str | None]:
    """(language, genre slug) of a game: the packs its names are read with."""
    row = await conn.fetchrow(
        """SELECT g.language, gr.slug FROM games AS g
           LEFT JOIN genres AS gr ON gr.id = g.genre_id
           WHERE g.id = $1""",
        game_id,
    )
    return (row["language"], row["slug"]) if row else (None, None)


async def label_taken(conn, game_id: UUID, entity_type: str, label: str) -> bool:
    """A live entity of the type holds `label` (normalised) as its registry label: the
    normalised uniqueness would refuse a second one."""
    return await conn.fetchval(
        """SELECT EXISTS (SELECT 1 FROM entity_registry
                           WHERE game_id = $1 AND entity_type = $2 AND merged_into IS NULL
                             AND name_norm = ldvelh_norm_for_game($1, $3))""",
        game_id,
        str(entity_type),
        label,
    )


async def label_holders(
    conn, game_id: UUID, entity_type: str, label: str
) -> dict[str, set[UUID]]:
    """{label norm: live entities of the type holding it} for the labels whose norm starts
    with `label`'s (its suffixed forms included): what a homonym suffix must avoid."""
    rows = await conn.fetch(
        """SELECT id, name_norm FROM entity_registry
           WHERE game_id = $1 AND entity_type = $2 AND merged_into IS NULL
             AND starts_with(name_norm, ldvelh_norm_for_game($1, $3))""",
        game_id,
        str(entity_type),
        label,
    )
    holders: dict[str, set[UUID]] = {}
    for r in rows:
        holders.setdefault(r["name_norm"], set()).add(r["id"])
    return holders


async def set_created_turn(conn, entity_id: UUID, turn_id: UUID) -> None:
    """The turn that created an entity, when the transaction's own turn did not set it."""
    await conn.execute(
        """UPDATE entity_registry SET created_turn_id = $2
           WHERE id = $1 AND created_turn_id IS DISTINCT FROM $2""",
        entity_id,
        turn_id,
    )


async def mark_aliases(
    conn, entity_id: UUID, *, known: bool | None = None, secret: bool = False
) -> None:
    """Every alias of an entity: `known` set (None: unchanged), secret when `secret`."""
    await conn.execute(
        """UPDATE entity_aliases SET known = COALESCE($2, known), secret = secret OR $3
           WHERE entity_id = $1""",
        entity_id,
        known,
        secret,
    )


async def handles(conn, entity_ids: list[UUID]) -> dict[UUID, int]:
    """E<n> handle of each id, read on its live entity (merges followed)."""
    rows = await conn.fetch(
        """SELECT ref.id, er.handle
           FROM unnest($1::uuid[]) AS ref (id)
           JOIN entity_registry AS er ON er.id = entity_follow_merge(ref.id)""",
        list(entity_ids),
    )
    return {r["id"]: r["handle"] for r in rows}


# Domain rows by id. Columns are checked against the table (pg_attribute), the identity
# columns are the service's: never taken from a caller's fields.
_IDENTITY_COLUMNS = frozenset(
    {"id", "game_id", "label_suffix", "created_at", "updated_at"}
)


async def domain_table(conn, entity_type: str) -> tuple[str, frozenset[str]]:
    """(table, writable columns) of an entity type's domain table."""
    table, columns = await _domain_columns(conn, entity_type)
    return table, columns - _IDENTITY_COLUMNS


def _stamp(table_columns: frozenset[str]) -> str:
    """The SET item that dates a domain update, for a table that has `updated_at`."""
    return ', "updated_at" = now()' if "updated_at" in table_columns else ""


async def _domain_columns(conn, entity_type: str) -> tuple[str, frozenset[str]]:
    """(table, every column) of an entity type's domain table."""
    rows = await conn.fetch(
        """SELECT identity_domain_table($1)::text AS tbl, att.attname
           FROM pg_attribute AS att
           WHERE att.attrelid = identity_domain_table($1) AND att.attnum > 0
             AND NOT att.attisdropped""",
        str(entity_type),
    )
    if not rows:
        raise ValueError(f"no domain table for entity type {entity_type!r}")
    return rows[0]["tbl"], frozenset(r["attname"] for r in rows)


def _checked(columns: frozenset[str], values: dict, table: str) -> list[str]:
    unknown = set(values) - columns
    if unknown:
        raise ValueError(f"{table}: columns not writable here: {sorted(unknown)}")
    return list(values)


async def insert_domain_row(
    conn, game_id: UUID, entity_type: str, values: dict, *, label_suffix: str | None
) -> UUID:
    """Insert an entity's domain row (its triggers register it); returns its id."""
    table, columns = await domain_table(conn, entity_type)
    names = _checked(columns, values, table)
    cols = ", ".join(["game_id", "label_suffix", *(f'"{c}"' for c in names)])
    marks = ", ".join(f"${i}" for i in range(1, len(names) + 3))
    return await conn.fetchval(
        f"INSERT INTO {table} ({cols}) VALUES ({marks}) RETURNING id",
        game_id,
        label_suffix,
        *values.values(),
    )


async def update_domain_row(
    conn,
    game_id: UUID,
    entity_type: str,
    entity_id: UUID,
    values: dict,
    *,
    label_suffix: SuffixChange | None = None,
) -> tuple[str, dict | None]:
    """(table, the row after the update as a dict, None when no row of the game has this
    id in the type's table). `label_suffix`: the internal suffix written in the same
    statement (R14), set or cleared; None leaves it as it is. `updated_at` is set."""
    table, all_columns = await _domain_columns(conn, entity_type)
    names = _checked(all_columns - _IDENTITY_COLUMNS, values, table)
    if not names:
        raise ValueError(f"{table}: nothing to update")
    values = dict(values)
    if label_suffix is not None:
        names.append("label_suffix")
        values["label_suffix"] = label_suffix.suffix
    sets = ", ".join(f'"{c}" = ${i}' for i, c in enumerate(names, start=3))
    sets += _stamp(all_columns)
    row = await conn.fetchrow(
        f"UPDATE {table} AS dom SET {sets} WHERE dom.id = $1 AND dom.game_id = $2"
        " RETURNING to_jsonb(dom) AS row",
        entity_id,
        game_id,
        *values.values(),
    )
    if row is None:
        return table, None
    value = row["row"]
    return table, value if isinstance(value, dict) else json.loads(value)


async def fill_domain_row(
    conn, game_id: UUID, entity_type: str, entity_id: UUID, values: dict
) -> bool:
    """Write `values` on an entity's domain row only when one of them differs from what is
    stored (no write, so no journal row, otherwise; `updated_at` set with a write); True
    when the row changed."""
    table, all_columns = await _domain_columns(conn, entity_type)
    names = _checked(all_columns - _IDENTITY_COLUMNS, values, table)
    if not names:
        return False
    sets = ", ".join(f'"{c}" = ${i}' for i, c in enumerate(names, start=3))
    sets += _stamp(all_columns)
    changed = " OR ".join(
        f'dom."{c}" IS DISTINCT FROM ${i}' for i, c in enumerate(names, start=3)
    )
    status = await conn.execute(
        f"UPDATE {table} AS dom SET {sets}"
        f" WHERE dom.id = $1 AND dom.game_id = $2 AND ({changed})",
        entity_id,
        game_id,
        *values.values(),
    )
    return status != "UPDATE 0"


async def live_candidates(
    conn, game_id: UUID, ref: str, entity_type: str
) -> list[UUID]:
    """Live entities of the type (merges followed, not removed from the world) whose
    label or alias has the normalised form of `ref`: find_entity's last step, restricted
    to the entities a write may target."""
    if ref is None or not ref.strip():
        return []
    ids = await conn.fetchval(
        """WITH ref AS (SELECT ldvelh_norm_for_game($1, $2) AS norm),
                candidates AS (
                    SELECT entity_follow_merge(er.id) AS id
                      FROM entity_registry AS er, ref
                     WHERE er.game_id = $1 AND er.entity_type = $3
                       AND er.name_norm = ref.norm
                    UNION
                    SELECT entity_follow_merge(al.entity_id)
                      FROM entity_aliases AS al, ref
                     WHERE al.game_id = $1 AND al.entity_type = $3
                       AND al.alias_norm = ref.norm)
           SELECT array_agg(id) FROM candidates
            WHERE identity_domain_row($3, id) IS NOT NULL
              AND (identity_domain_row($3, id) ->> 'removed_cycle') IS NULL""",
        game_id,
        ref,
        str(entity_type),
    )
    return list(ids or [])


async def removed_candidates(conn, game_id: UUID, ref: str, entity_type: str) -> int:
    """Entities of the type removed from the world (or without a domain row) whose label
    or alias has the normalised form of `ref`: what a live resolution left out, counted
    for telemetry."""
    if ref is None or not ref.strip():
        return 0
    return await conn.fetchval(
        """WITH ref AS (SELECT ldvelh_norm_for_game($1, $2) AS norm),
                candidates AS (
                    SELECT entity_follow_merge(er.id) AS id
                      FROM entity_registry AS er, ref
                     WHERE er.game_id = $1 AND er.entity_type = $3
                       AND er.name_norm = ref.norm
                    UNION
                    SELECT entity_follow_merge(al.entity_id)
                      FROM entity_aliases AS al, ref
                     WHERE al.game_id = $1 AND al.entity_type = $3
                       AND al.alias_norm = ref.norm)
           SELECT count(*) FROM candidates
            WHERE identity_domain_row($3, id) IS NULL
               OR (identity_domain_row($3, id) ->> 'removed_cycle') IS NOT NULL""",
        game_id,
        ref,
        str(entity_type),
    )


async def is_live(conn, entity_type: str, entity_id: UUID) -> bool:
    """The entity has a domain row that was not removed from the world (`removed_cycle`
    NULL, or a type without removal)."""
    row = await domain_row(conn, entity_type, entity_id)
    return row is not None and row.get("removed_cycle") is None


# Reveals and merges (spec §4.7).


async def domain_row(conn, entity_type: str, entity_id: UUID) -> dict | None:
    """An entity's domain row as a dict (None when it has none)."""
    value = await conn.fetchval(
        "SELECT identity_domain_row($1, $2)", str(entity_type), entity_id
    )
    if value is None:
        return None
    return value if isinstance(value, dict) else json.loads(value)


async def name_similarity(conn, game_id: UUID, first: str, second: str) -> float:
    """pg_trgm similarity of the normalised forms of two names (1 when the norms match)."""
    return await conn.fetchval(
        """SELECT similarity(ldvelh_norm_for_game($1, $2), ldvelh_norm_for_game($1, $3))""",
        game_id,
        first,
        second,
    )


async def name_holders(
    conn, game_id: UUID, entity_type: str, name: str, exclude: UUID
) -> list[UUID]:
    """Live entities of the type, `exclude` aside, that `name` (normalised) designates:
    a character only by a true name (its `true_name` aliases: never a descriptor, even an
    unnamed character's registry label, nor a short form), another entity by its registry
    label or a `label` alias."""
    rows = await conn.fetch(
        """WITH ref AS (SELECT ldvelh_norm_for_game($1, $3) AS norm)
           SELECT DISTINCT live.id
             FROM (SELECT er.id FROM entity_registry AS er, ref
                    WHERE er.game_id = $1 AND er.entity_type = $2
                      AND er.entity_type <> 'character' AND er.name_norm = ref.norm
                   UNION
                   SELECT al.entity_id FROM entity_aliases AS al, ref
                    WHERE al.game_id = $1 AND al.entity_type = $2
                      AND al.kind = CASE WHEN $2 = 'character' THEN 'true_name'
                                         ELSE 'label' END
                      AND al.alias_norm = ref.norm)
                  AS held (id)
             CROSS JOIN LATERAL (SELECT entity_follow_merge(held.id) AS id) AS live
            WHERE live.id IS DISTINCT FROM entity_follow_merge($4)""",
        game_id,
        str(entity_type),
        name,
        exclude,
    )
    return [r["id"] for r in rows]


async def label_held_by_other(
    conn, game_id: UUID, entity_type: str, label: str, exclude: UUID
) -> bool:
    """Another live entity of the type has `label` (normalised) as its registry label:
    giving it to `exclude` would break the registry's uniqueness."""
    return await conn.fetchval(
        """SELECT EXISTS (SELECT 1 FROM entity_registry
                           WHERE game_id = $1 AND entity_type = $2 AND merged_into IS NULL
                             AND id <> $4 AND name_norm = ldvelh_norm_for_game($1, $3))""",
        game_id,
        str(entity_type),
        label,
        exclude,
    )


async def set_character_known(conn, game_id: UUID, entity_id: UUID) -> bool:
    """The protagonist knows the character's true name; False when it already did."""
    changed = await conn.fetchval(
        """UPDATE characters SET known_by_protagonist = true, updated_at = now()
           WHERE id = $1 AND game_id = $2 AND known_by_protagonist IS NOT TRUE
           RETURNING id""",
        entity_id,
        game_id,
    )
    return changed is not None


async def mark_location_accessible(conn, game_id: UUID, location_id: UUID) -> bool:
    """Mark a location as accessible, by id; False when no location of the game has it."""
    result = await conn.execute(
        "UPDATE locations SET accessible = true, updated_at = NOW()"
        " WHERE id = $1 AND game_id = $2",
        location_id,
        game_id,
    )
    return result != "UPDATE 0"


async def mark_forms_known(conn, entity_id: UUID, forms: list[str]) -> int:
    """The entity's aliases with the normalised form of one of `forms` become known;
    returns how many changed."""
    rows = await conn.fetch(
        """UPDATE entity_aliases AS al SET known = true
           WHERE al.entity_id = $1 AND NOT al.known
             AND al.alias_norm IN (SELECT ldvelh_norm_for_game(al.game_id, form)
                                     FROM unnest($2::text[]) AS form)
           RETURNING al.id""",
        entity_id,
        list(forms),
    )
    return len(rows)


async def oldest(conn, entity_ids: list[UUID]) -> UUID:
    """The entity created first (domain created_at, then handle): world-gen before any
    later extraction."""
    return await conn.fetchval(
        """SELECT er.id FROM entity_registry AS er
           WHERE er.id = ANY($1::uuid[])
           ORDER BY (identity_domain_row(er.entity_type, er.id) ->> 'created_at')::timestamptz
                    NULLS LAST, er.handle
           LIMIT 1""",
        list(entity_ids),
    )


async def merge_entities(
    conn, keep_id: UUID, drop_id: UUID, reason: str | None, evidence: str | None
) -> UUID:
    """The SQL merge (journaled by the triggers); returns the entity_merges id."""
    return await conn.fetchval(
        "SELECT merge_entities($1, $2, $3, $4)", keep_id, drop_id, reason, evidence
    )


async def find_fact(conn, game_id: UUID, ref: str) -> UUID | None:
    """The fact `ref` names (F<n> handle or id), None otherwise."""
    if ref is None or not ref.strip():
        return None
    return await conn.fetchval("SELECT find_fact($1, $2)", game_id, ref)


async def set_fact_known(conn, game_id: UUID, fact_id: UUID) -> bool:
    """The protagonist knows the fact; False when it already did."""
    changed = await conn.fetchval(
        """UPDATE facts SET known = true WHERE id = $1 AND game_id = $2 AND NOT known
           RETURNING id""",
        fact_id,
        game_id,
    )
    return changed is not None


async def event_recorded(
    conn,
    game_id: UUID,
    kind: str,
    entity_id: UUID | None,
    turn_id: UUID | None,
    payload: dict,
) -> bool:
    """An identity_events row of this kind, entity and payload (jsonb equality) exists
    in this turn (without a turn: in this transaction)."""
    return await conn.fetchval(
        """SELECT EXISTS (SELECT 1 FROM identity_events
                           WHERE game_id = $1 AND kind = $2
                             AND entity_id IS NOT DISTINCT FROM $3
                             AND payload = $5::jsonb
                             AND CASE WHEN $4::uuid IS NULL
                                      THEN turn_id IS NULL AND created_at = now()
                                      ELSE turn_id = $4 END)""",
        game_id,
        kind,
        entity_id,
        turn_id,
        payload,
    )


async def restore_former_name(
    conn, entity_id: UUID, name: str, kind: str, known: bool
) -> None:
    """A former name the entity takes back is its name again (`kind`), with the known
    flag of its name: the name triggers' alias of it already exists, so they keep it a
    former name."""
    await conn.execute(
        """UPDATE entity_aliases AS al SET kind = $3, known = $4
           WHERE al.entity_id = $1 AND al.kind = 'former_name'
             AND al.alias_norm = ldvelh_norm_for_game(al.game_id, $2)""",
        entity_id,
        name,
        kind,
        known,
    )


class _DryRun(Exception):
    """Raised inside a savepoint to roll back a preview."""


async def edge_preview(
    conn, keep_id: UUID, drop_id: UUID, entity_type: str
) -> dict[str, int]:
    """The edges the SQL merge would move, as {"table.column": rows}, read from the merge's
    own `identity_merge_edges` run in a savepoint that is rolled back (so the preview can
    never drift from the merge). Nothing is written."""
    edges = {}
    try:
        async with conn.transaction():
            value = await conn.fetchval(
                "SELECT identity_merge_edges($1, $2, $3)",
                keep_id,
                drop_id,
                str(entity_type),
            )
            edges = value if isinstance(value, dict) else json.loads(value)
            raise _DryRun
    except _DryRun:
        pass
    return {key: len(ids) for key, ids in edges.items() if ids}


# Candidate blocking (spec §4.5.2). Every threshold is a parameter read from IdentityConfig,
# never a literal; a secret alias is matched and shown only for an entity of `disclosed`
# (an open disclosure). Candidates are live entities (merges followed), of any type.

# Alias kinds that name an entity: two entities sharing one are homonyms.
NAME_ALIAS_KINDS = ("label", "true_name")

# The aliases blocking may read: secret ones only for a disclosed entity.
_BLOCKING_ALIASES = """
    SELECT al.id AS alias_id, live.id AS entity_id, al.alias, al.alias_norm, al.kind,
           al.known, al.secret
      FROM entity_aliases AS al
     CROSS JOIN LATERAL (SELECT entity_follow_merge(al.entity_id) AS id) AS live
     WHERE al.game_id = $1
       AND (NOT al.secret OR live.id = ANY($2::uuid[]))"""


async def norm_for_game(conn, game_id: UUID, text: str) -> str:
    """`text` normalised with the pack of the game's language."""
    return await conn.fetchval("SELECT ldvelh_norm_for_game($1, $2)", game_id, text)


async def alias_max_words(conn, game_id: UUID) -> int:
    """Words of the longest alias of the game (0 without any)."""
    return await conn.fetchval(
        """SELECT coalesce(max(cardinality(string_to_array(alias_norm, ' '))), 0)
             FROM entity_aliases WHERE game_id = $1""",
        game_id,
    )


async def candidates_exact(
    conn, game_id: UUID, forms: list[str], *, disclosed: list[UUID]
) -> list[tuple[UUID, str]]:
    """(entity, norm) for each alias whose normalised form is the normalised form of one
    of `forms` (generator 1)."""
    rows = await conn.fetch(
        f"""WITH forms AS (SELECT DISTINCT ldvelh_norm_for_game($1, form) AS norm
                             FROM unnest($3::text[]) AS form),
                 aliases AS ({_BLOCKING_ALIASES})
            SELECT DISTINCT aliases.entity_id, forms.norm
              FROM aliases JOIN forms ON forms.norm = aliases.alias_norm""",
        game_id,
        list(disclosed),
        list(forms),
    )
    return [(r["entity_id"], r["norm"]) for r in rows]


# Generator 2. The words are looked up in the GIN index on (game_id, alias_norm
# gin_trgm_ops), which serves the game and the trigram predicates in one scan whatever the
# share of the game in the table; the secret and rich filters come after the
# MATERIALIZED step.
CANDIDATES_TRGM_SQL = f"""
    WITH near AS MATERIALIZED (
             SELECT al.id, given.word
               FROM unnest($3::text[]) AS given (word)
               JOIN entity_aliases AS al
                    ON al.game_id = $1 AND given.word <% al.alias_norm),
         aliases AS ({_BLOCKING_ALIASES}),
         pairs AS (
             SELECT aliases.alias_id, aliases.entity_id, aliases.alias_norm, near.word
               FROM near JOIN aliases ON aliases.alias_id = near.id
              WHERE (length(aliases.alias_norm) >= $4
                     OR cardinality(string_to_array(aliases.alias_norm, ' ')) > 1)
                AND strict_word_similarity(near.word, aliases.alias_norm) >= $5),
         parts AS (
             SELECT pairs.alias_id, pairs.entity_id, part.pos,
                    max(word_similarity(part.word, pairs.word)) AS best,
                    cardinality(show_trgm(part.word)) AS weight
               FROM pairs,
                    unnest(string_to_array(pairs.alias_norm, ' '))
                        WITH ORDINALITY AS part (word, pos)
              GROUP BY pairs.alias_id, pairs.entity_id, part.pos, part.word),
         covered AS (
             SELECT alias_id, entity_id,
                    sum(best * weight)::float / nullif(sum(weight), 0) AS score
               FROM parts GROUP BY alias_id, entity_id)
    SELECT entity_id, max(score) AS score FROM covered GROUP BY entity_id"""

_TRGM_THRESHOLD = "pg_trgm.word_similarity_threshold"


async def set_trgm_threshold(conn, config) -> str:
    """The word similarity threshold of `<%` set to `s_word` (local to the transaction);
    returns the previous value, for `restore_trgm_threshold`."""
    previous = await conn.fetchval("SELECT current_setting($1)", _TRGM_THRESHOLD)
    await conn.execute(
        "SELECT set_config($1, $2, true)", _TRGM_THRESHOLD, str(config.s_word)
    )
    return previous


async def restore_trgm_threshold(conn, previous: str) -> None:
    await conn.execute("SELECT set_config($1, $2, true)", _TRGM_THRESHOLD, previous)


async def candidates_trgm(
    conn, game_id: UUID, words: list[str], config, *, disclosed: list[UUID]
) -> list[tuple[UUID, float]]:
    """(entity, best score) of the rich aliases (at least `rich_min_chars` characters, or
    two words) that hold a fuzzy form of one of `words` (generator 2). The GIN trigram
    index finds the aliases in which a word reaches the word similarity `s_word`
    (`word <% alias_norm`); the word must also match whole words of the alias with a strict
    word similarity of at least `s_sim`. The score of an alias is the share of it the
    matched words cover together: each alias word takes its best match among them
    (`word_similarity(alias_word, word)`, credited once however many inflections the
    narration holds), weighted by its trigrams. A name whose every word is misspelled
    scores close to its exact form, not 1/n of it; a partial name stays below 1.

    Matching is per word: a word the caller left out (shorter than `token_min_len`, a
    stop word, a title, an article) cannot reach an alias here, and evidence spread over
    several narration words only adds up through the sum above. The threshold is set for
    the query only: the previous value is restored before returning, even inside a
    caller's transaction."""
    if not words:
        return []
    async with conn.transaction():
        previous = await set_trgm_threshold(conn, config)
        rows = await conn.fetch(
            CANDIDATES_TRGM_SQL,
            game_id,
            list(disclosed),
            list(words),
            config.rich_min_chars,
            config.s_sim,
        )
        await restore_trgm_threshold(conn, previous)
    return [(r["entity_id"], r["score"]) for r in rows]


async def candidates_tokens(
    conn, game_id: UUID, tokens: list[str], *, disclosed: list[UUID]
) -> list[tuple[UUID, float]]:
    """(entity, best share of an alias's words among `tokens`) of the aliases holding one
    of `tokens` as a word (generator 3; the caller left out stop words and titles)."""
    rows = await conn.fetch(
        f"""WITH aliases AS ({_BLOCKING_ALIASES}),
                 words AS (SELECT entity_id, string_to_array(alias_norm, ' ') AS words
                             FROM aliases)
            SELECT entity_id,
                   max((SELECT count(*) FROM unnest(words) AS word
                         WHERE word = ANY($3::text[]))::float
                       / cardinality(words)) AS score
              FROM words
             WHERE words && $3::text[]
             GROUP BY entity_id""",
        game_id,
        list(disclosed),
        list(tokens),
    )
    return [(r["entity_id"], r["score"]) for r in rows]


async def candidates_levenshtein(
    conn, game_id: UUID, tokens: list[str], config, *, disclosed: list[UUID]
) -> list[tuple[UUID, float]]:
    """(entity, score) of the aliases with a word of at least `lev_min_chars` characters
    within `lev_max` edits of a token as long (typos, generator 4). The score is the
    word's similarity (1 - edits / length) shared by the alias's words."""
    rows = await conn.fetch(
        f"""WITH aliases AS ({_BLOCKING_ALIASES}),
                 words AS (SELECT entity_id, string_to_array(alias_norm, ' ') AS words
                             FROM aliases),
                 near AS (
                     SELECT words.entity_id, cardinality(words.words) AS size, word,
                            levenshtein_less_equal(word, token, $5) AS edits
                       FROM words, unnest(words.words) AS word, unnest($3::text[]) AS token
                      WHERE length(word) >= $4 AND length(token) >= $4
                        AND abs(length(word) - length(token)) <= $5)
            SELECT entity_id, max((1 - edits::float / length(word)) / size) AS score
              FROM near
             WHERE edits <= $5
             GROUP BY entity_id""",
        game_id,
        list(disclosed),
        list(tokens),
        config.lev_min_chars,
        config.lev_max,
    )
    return [(r["entity_id"], r["score"]) for r in rows]


async def candidates_occupation(
    conn, game_id: UUID, text_norm: str, config
) -> list[tuple[UUID, float]]:
    """(entity, word similarity) of the characters and the protagonist whose normalised
    occupation is found in the normalised text with a word similarity at least `s_occ`
    (generator 6). Each distinct occupation is normalised and compared once."""
    rows = await conn.fetch(
        """WITH jobs AS (
                SELECT id, occupation FROM characters
                 WHERE game_id = $1 AND occupation IS NOT NULL
                UNION ALL
                SELECT id, occupation FROM protagonists
                 WHERE game_id = $1 AND occupation IS NOT NULL),
                normed AS MATERIALIZED (
                SELECT occupation, ldvelh_norm_for_game($1, occupation) AS norm
                  FROM (SELECT DISTINCT occupation FROM jobs) AS job),
                found AS MATERIALIZED (
                SELECT occupation, word_similarity(norm, $2) AS score
                  FROM normed WHERE norm <> '')
           SELECT jobs.id AS entity_id, found.score
             FROM jobs JOIN found USING (occupation)
            WHERE found.score >= $3""",
        game_id,
        text_norm,
        config.s_occ,
    )
    return [(r["entity_id"], r["score"]) for r in rows]


class ContextSource(NamedTuple):
    """Names of the context generator's sources (spec §4.5.2, generator 5)."""

    present: str = "present"
    reveal: str = "reveal"
    location: str = "location"
    mentioned: str = "mentioned"
    homonym: str = "homonym"
    planned: str = "planned"
    disclosed: str = "disclosed"
    companion: str = "companion"
    protagonist: str = "protagonist"


CONTEXT = ContextSource()


async def candidates_context(
    conn,
    game_id: UUID,
    *,
    location_id: UUID | None,
    present_ids: list[UUID],
    recent_message_ids: list[UUID],
    refs: list[tuple[str, str]],
    disclosed: list[UUID],
    protagonist_id: UUID,
    companion_id: UUID | None,
) -> list[tuple[UUID, str, int]]:
    """(entity, source, recency) of the scene's entities (generator 5), sources named by
    CONTEXT: present, the current location, entities mentioned in the recent messages
    (recency: the rank of the message, latest first, from 0), entities a reference of
    `refs` names exactly as (source, reference), disclosed, the protagonist, the companion,
    and the homonyms of those (another entity sharing a non-secret name alias with one).
    Recency is 0 outside the mentions."""
    rows = await conn.fetch(
        """WITH scene (id, source, recency) AS (
                SELECT id, $12, 0 FROM unnest($2::uuid[]) AS id
                UNION ALL SELECT $3::uuid, $13, 0 WHERE $3::uuid IS NOT NULL
                UNION ALL
                SELECT em.entity_id, $14,
                       (dense_rank() OVER (ORDER BY m.sequence DESC, m.created_at DESC))::int
                       - 1
                  FROM entity_mentions AS em JOIN messages AS m ON m.id = em.message_id
                 WHERE em.game_id = $1 AND em.message_id = ANY($4::uuid[])
                UNION ALL
                SELECT find_entity($1, ref.text, kind.entity_type), ref.source, 0
                  FROM unnest($5::text[], $6::text[]) AS ref (source, text),
                       unnest($7::text[]) AS kind (entity_type)
                UNION ALL SELECT id, $15, 0 FROM unnest($8::uuid[]) AS id
                UNION ALL SELECT $9::uuid, $16, 0
                UNION ALL SELECT $10::uuid, $17, 0 WHERE $10::uuid IS NOT NULL),
                homonym (id, source, recency) AS (
                SELECT DISTINCT other.entity_id, $18, 0
                  FROM scene
                  JOIN entity_aliases AS mine
                       ON mine.entity_id = scene.id AND mine.kind = ANY($11::text[])
                      AND NOT mine.secret
                  JOIN entity_aliases AS other
                       ON other.game_id = $1 AND other.alias_norm = mine.alias_norm
                      AND other.entity_id <> mine.entity_id
                      AND other.kind = ANY($11::text[]) AND NOT other.secret)
           SELECT live.id AS entity_id, scene.source, min(scene.recency) AS recency
             FROM (SELECT * FROM scene UNION ALL SELECT * FROM homonym) AS scene
            CROSS JOIN LATERAL (SELECT entity_follow_merge(scene.id) AS id) AS live
             JOIN entity_registry AS er ON er.id = live.id AND er.game_id = $1
            WHERE scene.id IS NOT NULL
            GROUP BY live.id, scene.source""",
        game_id,
        list(present_ids),
        location_id,
        list(recent_message_ids),
        [source for source, _ in refs],
        [ref for _, ref in refs],
        list(ANY_ENTITY_TYPES),
        list(disclosed),
        protagonist_id,
        companion_id,
        list(NAME_ALIAS_KINDS),
        CONTEXT.present,
        CONTEXT.location,
        CONTEXT.mentioned,
        CONTEXT.disclosed,
        CONTEXT.protagonist,
        CONTEXT.companion,
        CONTEXT.homonym,
    )
    return [(r["entity_id"], r["source"], r["recency"]) for r in rows]


async def live_handles(conn, game_id: UUID, entity_ids: list[UUID]) -> dict[UUID, int]:
    """E<n> handle of each id that is a live entity of the game (an id of another game or
    a merge tombstone has none)."""
    rows = await conn.fetch(
        """SELECT id, handle FROM entity_registry
            WHERE game_id = $1 AND id = ANY($2::uuid[]) AND merged_into IS NULL""",
        game_id,
        list(entity_ids),
    )
    return {r["id"]: r["handle"] for r in rows}


@dataclass(frozen=True)
class CardRow:
    """What a candidate card shows of an entity, aliases aside. `label_secret`: the label
    the player would read is a secret name of the entity (no open disclosure);
    `usual_location` is already blank when the place's own label is secret."""

    entity_id: UUID
    handle: int
    entity_type: str
    label: str
    occupation: str | None
    usual_location: str | None
    last_seen_turn: int | None
    description_line: str | None
    label_secret: bool = False


# The label `display_for_player` gives `{id}` is one of its secret aliases and no open
# disclosure lets the entity's secrets through ($3).
_LABEL_SECRET = """(NOT ({id} = ANY($3::uuid[])) AND EXISTS (
        SELECT 1 FROM entity_aliases AS sal
         WHERE sal.game_id = $1 AND sal.entity_id = {id} AND sal.secret
           AND sal.alias_norm = ldvelh_norm_for_game($1, display_for_player({id}))))"""
# What the player may read for `{id}` ($1 the game, $3 the disclosed entities): its
# display_for_player label, unless that is a secret name (_LABEL_SECRET); then its first
# non-secret descriptor, else a known non-secret alias; NULL for a whole-secret entity
# (the order of candidates._readable_label).
_READABLE_LABEL = (
    "CASE WHEN NOT "
    + _LABEL_SECRET
    + """ THEN display_for_player({id})
     ELSE (SELECT ral.alias FROM entity_aliases AS ral
            WHERE ral.game_id = $1 AND ral.entity_id = {id} AND NOT ral.secret
              AND (ral.kind = 'descriptor' OR ral.known)
            ORDER BY ral.kind = 'descriptor' DESC, ral.created_at, ral.alias_norm
            LIMIT 1) END"""
)


async def candidate_cards(
    conn, game_id: UUID, entity_ids: list[UUID], *, disclosed: list[UUID] = ()
) -> list[CardRow]:
    """Cards of live entities: what the player may read as label, occupation, usual place
    (workplace, residence, parent location or headquarters), the last turn it was mentioned
    in (rank of the latest assistant message mentioning it or an entity merged into it;
    None when never mentioned), first line of description. Mentions are read in one pass
    through the entity index, merges resolved once. Secrets stay filtered (spec §4.8): a
    label that is a secret name is flagged (`label_secret`, the caller replaces it), a
    usual place whose label is a secret name is left blank."""
    rows = await conn.fetch(
        f"""WITH RECURSIVE family (live, id) AS (
                SELECT id, id FROM unnest($2::uuid[]) AS id
                UNION
                SELECT family.live, er.id
                  FROM family JOIN entity_registry AS er ON er.merged_into = family.id
                 WHERE er.game_id = $1),
                turns AS (
                SELECT id, (row_number() OVER (ORDER BY sequence, created_at))::int AS turn
                  FROM messages WHERE game_id = $1 AND role = 'assistant'),
                seen AS (
                SELECT family.live, max(turns.turn) AS turn
                  FROM family
                  JOIN entity_mentions AS em ON em.entity_id = family.id
                  JOIN turns ON turns.id = em.message_id
                 GROUP BY family.live)
           SELECT er.id AS entity_id, er.handle, er.entity_type,
                  display_for_player(er.id) AS label,
                  {_LABEL_SECRET.format(id="er.id")} AS label_secret,
                  dom.row ->> 'occupation' AS occupation,
                  (SELECT display_for_player(place.id)
                     FROM entity_registry AS place
                    WHERE place.game_id = $1
                      AND place.id = coalesce((dom.row ->> 'workplace_id')::uuid,
                                              (dom.row ->> 'residence_id')::uuid,
                                              (dom.row ->> 'parent_id')::uuid,
                                              (dom.row ->> 'headquarters_id')::uuid)
                      AND NOT {_LABEL_SECRET.format(id="place.id")})
                      AS usual_location,
                  seen.turn AS last_seen_turn,
                  nullif(split_part(dom.row ->> 'description', E'\\n', 1), '')
                      AS description_line
             FROM entity_registry AS er
            CROSS JOIN LATERAL (SELECT identity_domain_row(er.entity_type, er.id) AS row)
                  AS dom
             LEFT JOIN seen ON seen.live = er.id
            WHERE er.game_id = $1 AND er.id = ANY($2::uuid[])""",
        game_id,
        list(entity_ids),
        list(disclosed),
    )
    return [CardRow(**dict(r)) for r in rows]


async def candidate_aliases(
    conn, game_id: UUID, entity_ids: list[UUID], *, disclosed: list[UUID]
) -> list[AliasRow]:
    """Aliases of the entities a card shows: unknown ordinary ones included, secret ones
    only for a disclosed entity."""
    rows = await conn.fetch(
        """SELECT al.id, live.id AS entity_id, al.entity_type, al.alias, al.alias_norm,
                  al.kind, al.known, al.secret, al.source, al.turn_id
             FROM entity_aliases AS al
            CROSS JOIN LATERAL (SELECT entity_follow_merge(al.entity_id) AS id) AS live
            WHERE al.game_id = $1 AND live.id = ANY($2::uuid[])
              AND (NOT al.secret OR live.id = ANY($3::uuid[]))
            ORDER BY al.created_at, al.alias_norm""",
        game_id,
        list(entity_ids),
        list(disclosed),
    )
    return [AliasRow(**dict(r)) for r in rows]


async def set_alias_flags(
    conn, entity_id: UUID, alias: str, *, known: bool, secret: bool
) -> None:
    """The entity's alias of the normalised form of `alias` takes these flags."""
    await conn.execute(
        """WITH form AS (SELECT ldvelh_norm_for_game(er.game_id, $2) AS norm
                           FROM entity_registry AS er WHERE er.id = $1)
           UPDATE entity_aliases AS al SET known = $3, secret = $4
             FROM form
            WHERE al.entity_id = $1 AND al.alias_norm = form.norm""",
        entity_id,
        alias,
        known,
        secret,
    )


# Resolver v2 application and extractor proposals (spec §4.5.6, §4.6).


# Alias kinds that hold an entity's whole name (never a derived short or untitled form).
FULL_NAME_KINDS = ("true_name", "label", "descriptor")


async def full_name_aliases(
    conn, game_id: UUID, entity_type: str
) -> list[tuple[UUID, str]]:
    """(live entity, alias) of the non-secret whole-name aliases (FULL_NAME_KINDS) of the
    live entities of the type, merges followed. The domain row is read once per entity,
    not per alias."""
    rows = await conn.fetch(
        """WITH named AS (
                SELECT DISTINCT entity_follow_merge(al.entity_id) AS id, al.alias
                  FROM entity_aliases AS al
                 WHERE al.game_id = $1 AND al.entity_type = $2 AND NOT al.secret
                   AND al.kind = ANY($3::text[])),
                alive AS (
                SELECT live.id
                  FROM (SELECT DISTINCT id FROM named) AS live
                 CROSS JOIN LATERAL (SELECT identity_domain_row($2, live.id) AS row) AS dom
                 WHERE dom.row IS NOT NULL AND (dom.row ->> 'removed_cycle') IS NULL)
           SELECT named.id AS entity_id, named.alias
             FROM named JOIN alive USING (id)""",
        game_id,
        str(entity_type),
        list(FULL_NAME_KINDS),
    )
    return [(r["entity_id"], r["alias"]) for r in rows]


async def bare_entities(conn, entity_ids: list[UUID]) -> dict[UUID, str]:
    """Type of each live entity of `entity_ids` whose row still has no description (a
    stub the extractors have not filled yet)."""
    if not entity_ids:
        return {}
    rows = await conn.fetch(
        """SELECT er.id, er.entity_type
             FROM entity_registry AS er
             CROSS JOIN LATERAL (SELECT identity_domain_row(er.entity_type, er.id) AS row)
                  AS dom
            WHERE er.id = ANY($1::uuid[]) AND er.merged_into IS NULL
              AND dom.row IS NOT NULL
              AND (dom.row ->> 'removed_cycle') IS NULL
              AND coalesce(btrim(dom.row ->> 'description'), '') = ''""",
        list(entity_ids),
    )
    return {r["id"]: r["entity_type"] for r in rows}


@dataclass(frozen=True)
class SceneEntityRow:
    entity_id: UUID
    handle: int
    entity_type: str
    label: str
    known: bool


async def scene_entity_rows(
    conn, game_id: UUID, entity_ids: list[UUID], *, disclosed: list[UUID] = ()
) -> list[SceneEntityRow]:
    """Handle, type, player-facing label and known flag of each entity (merges
    followed), in the order of `entity_ids`: a character is known when the protagonist
    knows its name, another entity when one of its non-secret aliases is known. A label
    that is a secret name is replaced like a card's, and a whole-secret entity (nothing
    readable) is left out: the extractors never see a secret (spec §4.8; `disclosed`:
    the entities an open disclosure lets through)."""
    if not entity_ids:
        return []
    rows = await conn.fetch(
        f"""SELECT DISTINCT ON (live.id) live.id AS entity_id, er.handle, er.entity_type,
                  {_READABLE_LABEL.format(id="live.id")} AS label,
                  coalesce((SELECT c.known_by_protagonist FROM characters AS c
                             WHERE c.id = live.id),
                           EXISTS (SELECT 1 FROM entity_aliases AS al
                                    WHERE al.entity_id = live.id AND al.known
                                      AND NOT al.secret)) AS known,
                  ids.ord
             FROM unnest($2::uuid[]) WITH ORDINALITY AS ids (id, ord)
             CROSS JOIN LATERAL (SELECT entity_follow_merge(ids.id) AS id) AS live
             JOIN entity_registry AS er ON er.id = live.id
            ORDER BY live.id, ids.ord""",
        game_id,
        list(entity_ids),
        list(disclosed),
    )
    ordered = sorted((r for r in rows if r["label"] is not None), key=lambda r: r["ord"])
    return [
        SceneEntityRow(
            r["entity_id"], r["handle"], r["entity_type"], r["label"], bool(r["known"])
        )
        for r in ordered
    ]


async def protagonist_and_companion(
    conn, game_id: UUID
) -> tuple[UUID | None, UUID | None]:
    """Ids of the game's protagonist and companion (None when it has none)."""
    row = await conn.fetchrow(
        """SELECT (SELECT id FROM entity_registry WHERE game_id = $1
                     AND entity_type = 'protagonist' AND merged_into IS NULL LIMIT 1)
                  AS protagonist,
                  (SELECT id FROM entity_registry WHERE game_id = $1
                     AND entity_type = 'companion' AND merged_into IS NULL LIMIT 1)
                  AS companion""",
        game_id,
    )
    return row["protagonist"], row["companion"]


async def reference_labels(conn, game_id: UUID) -> list[tuple[str, str]]:
    """(bare label, type) of the game's characters, locations and organizations, by type
    then label: the legacy resolver's first-turn reference."""
    rows = await conn.fetch(
        """SELECT identity_bare_label(er.id) AS name, er.entity_type
             FROM entity_registry er
            WHERE er.game_id = $1
              AND er.entity_type IN ('character', 'location', 'organization')
            ORDER BY er.entity_type, er.name""",
        game_id,
    )
    return [(r["name"], r["entity_type"]) for r in rows]


async def existing_entities(conn, game_id: UUID, entity_ids: list[UUID]) -> set[UUID]:
    """The ids of `entity_ids` that are entities of the game, not merge tombstones."""
    if not entity_ids:
        return set()
    rows = await conn.fetch(
        """SELECT id FROM entity_registry
            WHERE game_id = $1 AND id = ANY($2::uuid[]) AND merged_into IS NULL""",
        game_id,
        list(entity_ids),
    )
    return {r["id"] for r in rows}


# Relations that give a character a usual place.
PLACE_RELATIONS = ("works_at", "frequents", "lives_at")


async def known_places(conn, entity_ids: list[UUID]) -> dict[UUID, set[UUID]]:
    """The usual places of each character of `entity_ids`: its workplace, its residence
    and the targets of its open place relations (none: absent from the result)."""
    if not entity_ids:
        return {}
    rows = await conn.fetch(
        """SELECT c.id, place.id AS place
             FROM characters AS c
            CROSS JOIN LATERAL (VALUES (c.workplace_id), (c.residence_id)) AS place (id)
            WHERE c.id = ANY($1::uuid[]) AND place.id IS NOT NULL
           UNION
           SELECT r.source_id, r.target_id
             FROM relations AS r
            WHERE r.source_id = ANY($1::uuid[]) AND r.type::text = ANY($2::text[])
              AND r.end_cycle IS NULL""",
        list(entity_ids),
        list(PLACE_RELATIONS),
    )
    places: dict[UUID, set[UUID]] = {}
    for r in rows:
        places.setdefault(r["id"], set()).add(r["place"])
    return places


async def characters_at(conn, game_id: UUID, location_id: UUID) -> list[UUID]:
    """The characters, not removed from the world, whose open place relation (works at,
    frequents, lives at) points at the location."""
    rows = await conn.fetch(
        """SELECT DISTINCT c.id
             FROM characters AS c
             JOIN relations AS r ON r.source_id = c.id AND r.target_id = $2
                  AND r.type::text = ANY($3::text[]) AND r.end_cycle IS NULL
            WHERE c.game_id = $1 AND c.removed_cycle IS NULL""",
        game_id,
        location_id,
        list(PLACE_RELATIONS),
    )
    return [r["id"] for r in rows]


async def mentioned_elsewhere(
    conn, game_id: UUID, entity_ids: list[UUID], message_id: UUID
) -> set[UUID]:
    """The ids of `entity_ids` that a message other than `message_id` mentions (merges
    followed)."""
    if not entity_ids:
        return set()
    rows = await conn.fetch(
        """SELECT DISTINCT entity_follow_merge(entity_id) AS id FROM entity_mentions
            WHERE game_id = $3 AND message_id <> $2
              AND entity_follow_merge(entity_id) = ANY($1::uuid[])""",
        list(entity_ids),
        message_id,
        game_id,
    )
    return {r["id"] for r in rows}


async def carried_by_protagonist(
    conn, game_id: UUID, entity_ids: list[UUID]
) -> set[UUID]:
    """The objects of `entity_ids` the protagonist carries: a row of the protagonist's
    inventory (inventory.owner_id NULL; NPC possessions are not kept)."""
    rows = await conn.fetch(
        """SELECT DISTINCT object_id FROM inventory
            WHERE game_id = $1 AND owner_id IS NULL AND object_id = ANY($2::uuid[])""",
        game_id,
        list(entity_ids),
    )
    return {r["object_id"] for r in rows}


async def insert_protagonist_item(conn, game_id: UUID, object_id: UUID) -> None:
    """One `object_id` in the protagonist's inventory (owner_id NULL)."""
    await conn.execute(
        "INSERT INTO inventory (game_id, object_id, quantity) VALUES ($1, $2, 1)",
        game_id,
        object_id,
    )
