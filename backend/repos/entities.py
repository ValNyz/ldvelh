"""Entity identity repository: references, registry rows, aliases, mentions and events.

Every lookup of an entity by a reference goes through the SQL `find_entity`, which needs
the entity type: a handle `E<n>`, an id, PROTAGONIST/COMPANION, else the normalised
labels and aliases of that type. Two matches or more give None (ambiguous), never an
arbitrary pick (spec §4.2). No function opens a connection or a transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

logger = logging.getLogger(__name__)

# Order in which an untyped reference (a fact participant, a relation end) is tried: the
# first type that resolves it wins. Homonyms of two types are legitimate (spec §4.10);
# within one type, an ambiguity stays None.
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
    was ambiguous (then nothing must be created under it)."""

    entity_id: UUID | None
    by_label: bool
    ambiguous: bool


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


async def find_any(
    conn, game_id: UUID, ref: str | None, types: tuple[str, ...] = ANY_ENTITY_TYPES
) -> tuple[UUID, str] | None:
    """(id, type) of an untyped reference: the typed find_entity of each type of `types`,
    the first one resolving it wins. None when no type resolves it (unknown, or ambiguous
    within each type that knows it), logged at INFO without the reference."""
    if ref is None or not ref.strip():
        return None
    rows = await conn.fetch(
        """SELECT t.entity_type, find_entity($1, $2, t.entity_type) AS id
             FROM unnest($3::text[]) WITH ORDINALITY AS t (entity_type, rank)
            ORDER BY t.rank""",
        game_id,
        ref,
        list(types),
    )
    for row in rows:
        if row["id"] is not None:
            return row["id"], row["entity_type"]
    logger.info("[IDENTITY] reference unresolved (unknown or ambiguous)")
    return None


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
        return UpsertTarget(row["owner"], True, False)
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
