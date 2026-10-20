"""The scene of a turn as the resolver v2 reads it (spec §4.5.1): where it happens, who
is there, what the previous narrator messages named, what the narrator revealed and whom
the Director plans to bring in.

The current place is the message's own, else the game's; the characters present are those
the knowledge graph places there (get_npcs_at_location) and those the narrator lists as
present. Recent messages are the K = IdentityConfig.context_messages narrator messages
before this one, whose entity_mentions the context generator reads.
"""

from __future__ import annotations

from uuid import UUID

from config import IdentityConfig, get_identity_config
from domain.identity import SceneContext
from kg.reader import KnowledgeGraphReader
from repos import entities, games, messages

CHARACTER = "character"


def _names(values) -> list[str]:
    return [v for v in values or () if isinstance(v, str) and v.strip()]


async def _present(
    conn, game_id: UUID, location_id: UUID | None, narrator_deltas: dict
) -> list[UUID]:
    """Characters at the place (by its id) and the ones the narrator lists, once each."""
    present: list[UUID] = []
    if location_id is not None:
        reader = KnowledgeGraphReader(None, game_id)
        for npc in await reader.get_npcs_at_location(conn, str(location_id)):
            present.append(npc["id"])
    for name in _names(narrator_deltas.get("npcs_present")):
        entity_id = await entities.find_entity(conn, game_id, name, CHARACTER)
        if entity_id is not None:
            present.append(entity_id)
    return list(dict.fromkeys(present))


def _reveal_refs(narrator_deltas: dict) -> list[str]:
    reveals = narrator_deltas.get("entity_reveals") or []
    return _names(r.get("current_name") for r in reveals if isinstance(r, dict))


async def _planned_npcs(conn, game_id: UUID) -> list[str]:
    return [
        name
        for event in await games.latest_planned_events(conn, game_id)
        for name in _names(event.get("npcs_involved"))
    ]


async def collect_scene_context(
    conn,
    game_id: UUID,
    message_id: UUID,
    narrator_deltas: dict | None,
    *,
    config: IdentityConfig | None = None,
) -> SceneContext:
    """The SceneContext of the narrator message `message_id` (spec §4.5.1)."""
    config = config or get_identity_config()
    deltas = narrator_deltas or {}
    location_id = await messages.scene_location(conn, game_id, message_id)
    protagonist_id, companion_id = await entities.protagonist_and_companion(
        conn, game_id
    )
    _, genre = await entities.game_language(conn, game_id)
    return SceneContext(
        location_id=location_id,
        present_ids=await _present(conn, game_id, location_id, deltas),
        recent_message_ids=await messages.recent_assistant_messages(
            conn, game_id, message_id, config.context_messages
        ),
        reveal_refs=_reveal_refs(deltas),
        planned_npc_handles=await _planned_npcs(conn, game_id),
        # Disclosures open with the Director's secrets (PR 4): none yet.
        open_disclosure_ids=[],
        protagonist_id=protagonist_id,
        companion_id=companion_id,
        genre=genre,
    )
