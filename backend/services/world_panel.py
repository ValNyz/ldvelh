"""World panel (`/games/{id}/world`, ruling R51): what the player may read of the world's
NPCs, places and organizations, by the visibility rules of the tooltips (spec §4.9).

Every active NPC is listed under what the player may read (display_for_player, a secret
name replaced), with `known`: whether the protagonist has identified it. An NPC the
protagonist has not identified shows no occupation, description (they may name it) nor
relation (spec §4.9).
A place or an organization is listed under its readable label (a whole-secret one with a
readable descriptor under that descriptor); an entity with nothing readable is left out.
A detail whose text holds one of the entity's hidden names is left out, and a place named
by an entry (an NPC's place, a place's parent) is shown under its readable label, or not
at all.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from uuid import UUID

from repos import entities
from repos.entities import TooltipRow
from services.tooltips import identified

_OCCUPATION = "occupation"
_DESCRIPTION = "description"
_LOCATION_TYPE = "location_type"
_SECTOR = "sector"
_ORG_TYPE = "org_type"
_DOMAIN = "domain"
# The detail keys each list prints, checked against the entity's hidden names; a place an
# entry only names (an NPC's place, a place's parent) shows its label alone.
NPC_FIELDS = (_OCCUPATION, _DESCRIPTION)
LOCATION_FIELDS = (_LOCATION_TYPE, _SECTOR)
ORGANIZATION_FIELDS = (_ORG_TYPE, _DOMAIN)

Rows = dict[UUID, TooltipRow]


async def readable_rows(
    conn, game_id: UUID, ids: Iterable[UUID | None], fields: tuple[str, ...] = ()
) -> Rows:
    """The tooltip sources of `ids` (None skipped), keyed by id, `fields` checked."""
    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    return await entities.tooltip_rows(conn, game_id, wanted, list(fields))


async def load_npcs(
    conn, game_id: UUID, characters: list[dict], relation_label: Callable
) -> list[dict]:
    """npc_entries of the active NPCs (reader rows) of the game."""
    rows = await readable_rows(conn, game_id, (c["id"] for c in characters), NPC_FIELDS)
    places = await readable_rows(conn, game_id, (_place_id(c) for c in characters))
    return npc_entries(characters, rows, places, relation_label)


async def load_locations(conn, game_id: UUID, locations: list[dict]) -> list[dict]:
    """location_entries of the active places (reader rows) of the game."""
    ids = [loc["id"] for loc in locations]
    rows = await readable_rows(conn, game_id, ids, LOCATION_FIELDS)
    parents = [loc.get("parent_id") for loc in locations]
    missing = await readable_rows(conn, game_id, (p for p in parents if p not in rows))
    return location_entries(locations, rows, {**missing, **rows})


async def load_organizations(
    conn, game_id: UUID, organizations: list[dict]
) -> list[dict]:
    """organization_entries of the active organizations (reader rows) of the game."""
    ids = [org["id"] for org in organizations]
    rows = await readable_rows(conn, game_id, ids, ORGANIZATION_FIELDS)
    return organization_entries(organizations, rows)


def _label(rows: Rows, entity_id: UUID | None) -> str | None:
    """What the player may read of `entity_id`; None when nothing (or no such id)."""
    row = rows.get(entity_id) if entity_id is not None else None
    return row.label if row is not None else None


def _detail(row: TooltipRow, source: dict, key: str) -> str | None:
    """`source[key]`, unless its text holds one of the entity's hidden names."""
    return None if key in row.hidden_fields else source.get(key)


def _place_id(character: dict) -> UUID | None:
    """The place an NPC entry names: its workplace, else its first spatial relation."""
    return character.get("workplace_id") or character.get("usual_location_id")


def npc_entries(
    characters: list[dict],
    rows: Rows,
    places: Rows,
    relation_label: Callable[[int | None], str],
) -> list[dict]:
    """The panel entries of the active NPCs (reader rows), in their order: `rows` their
    tooltip sources, `places` those of the places they name. An NPC the protagonist has
    not identified shows neither occupation, description nor relation (spec §4.9)."""
    entries = []
    for c in characters:
        row = rows.get(c["id"])
        if row is None or row.label is None:
            continue
        known = identified(row)
        level = c.get("relation_level")
        entries.append(
            {
                "id": str(c["id"]),
                "name": row.label,
                "known": known,
                "occupation": _detail(row, c, _OCCUPATION) if known else None,
                "location": _label(places, _place_id(c)),
                "relationship": relation_label(level) if known else None,
                "relation_level": level if known else None,
                "description": _detail(row, c, _DESCRIPTION) if known else None,
            }
        )
    return entries


def location_entries(locations: list[dict], rows: Rows, parents: Rows) -> list[dict]:
    """The panel entries of the active places (reader rows), in their order: `rows`
    their tooltip sources, `parents` those of their parents."""
    entries = []
    for loc in locations:
        row = rows.get(loc["id"])
        if row is None or row.label is None:
            continue
        entries.append(
            {
                "id": str(loc["id"]),
                "name": row.label,
                "type": _detail(row, loc, _LOCATION_TYPE),
                "sector": _detail(row, loc, _SECTOR),
                "parent": _label(parents, loc.get("parent_id")),
                "accessible": loc.get("accessible", True),
            }
        )
    return entries


def organization_entries(organizations: list[dict], rows: Rows) -> list[dict]:
    """The panel entries of the active organizations (reader rows), in their order."""
    entries = []
    for org in organizations:
        row = rows.get(org["id"])
        if row is None or row.label is None:
            continue
        entries.append(
            {
                "id": str(org["id"]),
                "name": row.label,
                "type": _detail(row, org, _ORG_TYPE),
                "domain": _detail(row, org, _DOMAIN),
            }
        )
    return entries
