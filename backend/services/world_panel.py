"""World panel (`/games/{id}/world`, ruling R51): what the player may read of the world's
NPCs, places and organizations, by the visibility rules of the tooltips (spec §4.9).

Every active NPC is listed under what the player may read (display_for_player, a secret
name replaced), with `known`: whether the protagonist has identified it. An NPC the
protagonist has not identified shows no occupation nor description (they may name it).
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
# Every detail key an entry may print: each is checked against the entity's hidden names.
CHECKED_FIELDS = sorted(
    {_OCCUPATION, _DESCRIPTION, _LOCATION_TYPE, _SECTOR, _ORG_TYPE, _DOMAIN}
)

Rows = dict[UUID, TooltipRow]


async def readable_rows(conn, game_id: UUID, ids: Iterable[UUID | None]) -> Rows:
    """The tooltip sources of `ids` (None skipped), keyed by id."""
    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    return await entities.tooltip_rows(conn, game_id, wanted, CHECKED_FIELDS)


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


def npc_refs(characters: list[dict]) -> list[UUID | None]:
    """The ids npc_entries reads: the NPCs and the places they name."""
    return [c["id"] for c in characters] + [_place_id(c) for c in characters]


def location_refs(locations: list[dict]) -> list[UUID | None]:
    """The ids location_entries reads: the places and their parents."""
    return [loc["id"] for loc in locations] + [
        loc.get("parent_id") for loc in locations
    ]


def npc_entries(
    characters: list[dict], rows: Rows, relation_label: Callable[[int | None], str]
) -> list[dict]:
    """The panel entries of the active NPCs (reader rows), in their order."""
    entries = []
    for c in characters:
        row = rows.get(c["id"])
        if row is None or row.label is None:
            continue
        known = identified(row)
        entries.append(
            {
                "id": str(c["id"]),
                "name": row.label,
                "known": known,
                "occupation": _detail(row, c, _OCCUPATION) if known else None,
                "location": _label(rows, _place_id(c)),
                "relationship": relation_label(c.get("relation_level")),
                "relation_level": c.get("relation_level"),
                "description": _detail(row, c, _DESCRIPTION) if known else None,
            }
        )
    return entries


def location_entries(locations: list[dict], rows: Rows) -> list[dict]:
    """The panel entries of the active places (reader rows), in their order."""
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
                "parent": _label(rows, loc.get("parent_id")),
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
