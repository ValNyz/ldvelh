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
from uuid import UUID

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
class MentionRow:
    start_pos: int
    end_pos: int
    surface: str
    entity_id: UUID
    decision: str
    evidence: str | None = None
    entity_type: str | None = None  # set on read
    label: str | None = None  # display_for_player, set on read


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
    conn, game_id: UUID, ref: str | None, types: tuple[str, ...] = ANY_ENTITY_TYPES
) -> tuple[UUID, str] | None:
    """(id, type) of an untyped reference, only when exactly one type of `types` knows it
    and knows it once. A reference that two types know, or that two entities of one type
    share (labels and aliases together, as find_entity), is ambiguous: None, so an
    ambiguity among characters never falls through to a location of the same name. The
    outcome is logged at INFO with counts only (the reference is story text)."""
    if ref is None or not ref.strip():
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
    conn, game_id: UUID, ref: str, types: tuple[str, ...]
) -> dict[str, int]:
    """Live entities of each type of `types` whose label or alias has the normalised form
    of `ref` (merges followed): find_entity's last step, counted (2 or more: ambiguous)."""
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
             FROM candidates GROUP BY entity_type""",
        game_id,
        ref,
        list(types),
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


async def follow_merge(conn, entity_id: UUID) -> UUID:
    """The live entity behind `entity_id` (merge tombstones followed)."""
    return await conn.fetchval("SELECT entity_follow_merge($1)", entity_id)


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
    conn, game_id: UUID, message_ids: list[UUID]
) -> dict[UUID, list[MentionRow]]:
    """Spans of each message, in text order, on the live entity (merges followed), with
    the name the player may read as label."""
    if not message_ids:
        return {}
    rows = await conn.fetch(
        """SELECT m.message_id, m.start_pos, m.end_pos, m.surface, m.decision, m.evidence,
                  live.id AS entity_id, er.entity_type, display_for_player(live.id) AS label
           FROM entity_mentions AS m
           CROSS JOIN LATERAL (SELECT entity_follow_merge(m.entity_id) AS id) AS live
           JOIN entity_registry AS er ON er.id = live.id
           WHERE m.game_id = $1 AND m.message_id = ANY($2::uuid[])
           ORDER BY m.message_id, m.start_pos, m.end_pos""",
        game_id,
        list(message_ids),
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


async def clear_label_suffix(conn, entity_type: str, entity_id: UUID) -> None:
    """Drop an entity's internal label suffix (its triggers update the registry label)."""
    table, _ = await domain_table(conn, entity_type)
    await conn.execute(
        f"UPDATE {table} SET label_suffix = NULL WHERE id = $1", entity_id
    )


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
    rows = await conn.fetch(
        """SELECT identity_domain_table($1)::text AS tbl, att.attname
           FROM pg_attribute AS att
           WHERE att.attrelid = identity_domain_table($1) AND att.attnum > 0
             AND NOT att.attisdropped""",
        str(entity_type),
    )
    if not rows:
        raise ValueError(f"no domain table for entity type {entity_type!r}")
    return rows[0]["tbl"], frozenset(r["attname"] for r in rows) - _IDENTITY_COLUMNS


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
    conn, game_id: UUID, entity_type: str, entity_id: UUID, values: dict
) -> tuple[str, dict | None]:
    """(table, the row after the update as a dict, None when no row of the game has this
    id in the type's table)."""
    table, columns = await domain_table(conn, entity_type)
    names = _checked(columns, values, table)
    if not names:
        raise ValueError(f"{table}: nothing to update")
    sets = ", ".join(f'"{c}" = ${i}' for i, c in enumerate(names, start=3))
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
    """Live entities of the type, `exclude` aside, that hold `name` (normalised) as their
    registry label or as a true-name or label alias: the ones a revealed name designates."""
    rows = await conn.fetch(
        """WITH ref AS (SELECT ldvelh_norm_for_game($1, $3) AS norm)
           SELECT DISTINCT live.id
             FROM (SELECT er.id FROM entity_registry AS er, ref
                    WHERE er.game_id = $1 AND er.entity_type = $2
                      AND er.name_norm = ref.norm
                   UNION
                   SELECT al.entity_id FROM entity_aliases AS al, ref
                    WHERE al.game_id = $1 AND al.entity_type = $2
                      AND al.kind IN ('true_name', 'label') AND al.alias_norm = ref.norm)
                  AS held (id)
             CROSS JOIN LATERAL (SELECT entity_follow_merge(held.id) AS id) AS live
            WHERE live.id IS DISTINCT FROM entity_follow_merge($4)""",
        game_id,
        str(entity_type),
        name,
        exclude,
    )
    return [r["id"] for r in rows]


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
    conn, game_id: UUID, kind: str, entity_id: UUID | None, turn_id: UUID
) -> bool:
    """An identity_events row of this kind, entity and turn exists already."""
    return await conn.fetchval(
        """SELECT EXISTS (SELECT 1 FROM identity_events
                           WHERE game_id = $1 AND kind = $2 AND turn_id = $4
                             AND entity_id IS NOT DISTINCT FROM $3)""",
        game_id,
        kind,
        entity_id,
        turn_id,
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
