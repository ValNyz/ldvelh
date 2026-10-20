"""Loads a gold scene's world into a game, as the blocking reads it (#154, spec §4.5).

`load_world` creates the protagonist and the companion as game creation does (their domain
row), every other entity of the `world` snapshot through the identity service (derived
aliases, then the snapshot's own with their flags), and one assistant message
per past turn: the `history` messages for the last turns, with their gold mentions; for
the earlier turns, a message that mentions each entity last seen in that turn, so that
the entity's last turn and the recent messages read like those of a game. An arc is not
an entity of the registry: it is skipped (its mentions cannot be candidates).

The returned map holds the uuid of each world id, and of each past turn's message under
`turn_key(n)`. `scene_context` builds the SceneContext of a scene from it.
"""

from __future__ import annotations

from uuid import UUID

from config import get_identity_config
from domain.identity import NewEntitySpec, SceneContext
from evals.identity.corpus import HistoryMessage, Scene, WorldEntity
from repos import entities, messages
from repos.entities import MentionRow
from services.identity.service import IdentityService

SOURCE = "world_gen"
ASSISTANT = "assistant"
PROTAGONIST, COMPANION, CHARACTER = "protagonist", "companion", "character"
LOCATION, ORGANIZATION = "location", "organization"
NAME_DISCLOSURE = "name"
_LINKS = {"MATCH": "match", "ALIAS": "alias"}
_TURN_PREFIX = "turn:"
# Types the identity service creates (world order, a place before what refers to it).
CREATED = (LOCATION, ORGANIZATION, CHARACTER, "object")


def turn_key(turn: int) -> str:
    """Key of a past turn's assistant message in the map of `load_world`."""
    return f"{_TURN_PREFIX}{turn}"


def _turn_of(key: str) -> int | None:
    return int(key[len(_TURN_PREFIX) :]) if key.startswith(_TURN_PREFIX) else None


async def load_world(
    conn,
    game_id: UUID,
    world: list[WorldEntity],
    history: list[HistoryMessage],
    *,
    turn: int | None = None,
) -> dict[str, UUID]:
    """Entities and past messages of a scene in `game_id`; {world id or turn key: uuid}.
    `turn`: the scene's turn (default: after the last turn the world or history knows)."""
    service = await IdentityService.for_game(conn, game_id)
    ids: dict[str, UUID] = {}
    for entity in world:
        if entity.type in (PROTAGONIST, COMPANION):
            fields = {"name": entity.label}
            if entity.type == PROTAGONIST and entity.occupation:
                fields["occupation"] = entity.occupation
            ids[entity.id] = await entities.insert_domain_row(
                conn, game_id, entity.type, fields, label_suffix=None
            )
    by_id = {e.id: e for e in world if e.type in CREATED}
    for entity in by_id.values():
        await _create_with_place(conn, service, entity, by_id, ids, set())
    for entity in world:
        if entity.id in ids:
            await _add_aliases(conn, service, entity, ids[entity.id])
    current = turn or max([len(history), *(e.last_seen_turn or 0 for e in world)]) + 1
    ids.update(await _messages(conn, game_id, world, history, ids, current))
    return ids


def _spec(
    entity: WorldEntity, ids: dict[str, UUID], places: frozenset[str]
) -> NewEntitySpec:
    """The creation of a world entity; its `location`, when a world location, is a
    character's workplace, a location's parent or an organization's headquarters."""
    place = ids.get(entity.location) if entity.location in places else None
    fields: dict = {}
    if entity.type == CHARACTER:
        if entity.occupation:
            fields["occupation"] = entity.occupation
        if place is not None:
            fields["workplace_id"] = place
        if entity.true_name:
            return NewEntitySpec(
                CHARACTER,
                entity.true_name,
                "proper_name",
                known=entity.known,
                secret=entity.secret,
                descriptor=entity.descriptor,
                fields=fields,
            )
        return NewEntitySpec(
            CHARACTER,
            entity.descriptor or entity.label,
            "descriptor",
            secret=entity.secret,
            fields=fields,
        )
    if place is not None and entity.type == LOCATION:
        fields["parent_id"] = place
    if place is not None and entity.type == ORGANIZATION:
        fields["headquarters_id"] = place
    return NewEntitySpec(
        entity.type,
        entity.label,
        "proper_name",
        known=entity.known,
        secret=entity.secret,
        fields=fields,
    )


async def _create_with_place(
    conn,
    service: IdentityService,
    entity: WorldEntity,
    by_id: dict[str, WorldEntity],
    ids: dict[str, UUID],
    path: set[str],
) -> None:
    """Create `entity` in world order, the place it refers to first (a cycle of places
    leaves the last one without its place)."""
    if entity.id in ids or entity.id in path:
        return
    place = by_id.get(entity.location or "")
    if place is not None and place.type == LOCATION:
        await _create_with_place(conn, service, place, by_id, ids, path | {entity.id})
    places = frozenset(i for i, e in by_id.items() if e.type == LOCATION)
    ids[entity.id] = await _create(conn, service, _spec(entity, ids, places), ids)


async def _create(
    conn, service: IdentityService, spec: NewEntitySpec, ids: dict[str, UUID]
) -> UUID:
    """A world entity is always a distinct entity: a label another one holds makes a
    homonym (verified trap), never a reuse."""
    entity_id = await service.create_entity(
        conn, spec, turn_id=None, source=SOURCE, reuse_aliases=False
    )
    if entity_id in ids.values():
        entity_id = await service.create_entity(
            conn, spec, turn_id=None, source=SOURCE, trap=True
        )
    return entity_id


async def _add_aliases(
    conn, service: IdentityService, entity: WorldEntity, entity_id: UUID
) -> None:
    """The snapshot's aliases, with its flags (a derived alias of the same form takes
    them)."""
    for alias in entity.aliases:
        secret = alias.secret or entity.secret
        await service.add_alias(
            conn,
            entity_id,
            alias.text,
            alias.kind,
            known=alias.known,
            secret=secret,
            source=SOURCE,
        )
        await entities.set_alias_flags(
            conn, entity_id, alias.text, known=alias.known, secret=secret
        )


def _seen_in_history(history: list[HistoryMessage], first: int) -> dict[str, int]:
    """Latest history turn mentioning each world id."""
    seen = {}
    for offset, message in enumerate(history):
        for mention in message.mentions:
            parsed = mention.parsed
            if parsed.decision in _LINKS:
                seen[parsed.entity_id] = first + offset
    return seen


async def _messages(
    conn,
    game_id: UUID,
    world: list[WorldEntity],
    history: list[HistoryMessage],
    ids: dict[str, UUID],
    current: int,
) -> dict[str, UUID]:
    """One assistant message per past turn: history for the last ones, before them a
    message mentioning the entities last seen in that turn."""
    first = current - len(history)
    seen = _seen_in_history(history, first)
    earlier: dict[int, list[WorldEntity]] = {}
    for entity in world:
        last = entity.last_seen_turn
        if entity.id in ids and last and last < first and seen.get(entity.id, 0) < last:
            earlier.setdefault(last, []).append(entity)
    conversation = await messages.insert_conversation(conn, game_id, 1)
    keys = {}
    for turn in range(1, current):
        if turn >= first:
            message = history[turn - first]
            text = message.text
            mentions = [
                MentionRow(
                    m.start,
                    m.start + len(m.surface),
                    m.surface,
                    ids[m.parsed.entity_id],
                    _LINKS[m.parsed.decision],
                )
                for m in message.mentions
                if m.parsed.decision in _LINKS and m.parsed.entity_id in ids
            ]
        else:
            text, mentions = _filler(earlier.get(turn, []), ids)
        message_id = await messages.insert_message(
            conn, game_id, conversation, ASSISTANT, text, turn
        )
        await entities.insert_mentions(conn, game_id, message_id, None, mentions)
        keys[turn_key(turn)] = message_id
    return keys


def _filler(
    seen: list[WorldEntity], ids: dict[str, UUID]
) -> tuple[str, list[MentionRow]]:
    """A message naming each entity of `seen` by its label, one per line."""
    lines, mentions, start = [], [], 0
    for entity in seen:
        mentions.append(
            MentionRow(
                start,
                start + len(entity.label),
                entity.label,
                ids[entity.id],
                _LINKS["MATCH"],
            )
        )
        lines.append(entity.label)
        start += len(entity.label) + 1
    return "\n".join(lines), mentions


def scene_context(
    scene: Scene, ids: dict[str, UUID], *, context_messages: int | None = None
) -> SceneContext:
    """The SceneContext of `scene` once `load_world` loaded it. Reveals and planned NPCs
    keep their reference as given when it is not a world id. `context_messages`: K, the
    recent messages read (default: IdentityConfig)."""
    k = context_messages or get_identity_config().context_messages
    turns = sorted((t for key in ids if (t := _turn_of(key)) is not None), reverse=True)
    info = scene.scene

    def ref(value: str) -> str:
        return str(ids[value]) if value in ids else value

    def of_type(entity_type: str) -> UUID | None:
        return next(
            (ids[e.id] for e in scene.world if e.type == entity_type and e.id in ids),
            None,
        )

    protagonist = of_type(PROTAGONIST)
    if protagonist is None:
        raise ValueError(f"scene {scene.id} has no protagonist")
    return SceneContext(
        location_id=ids.get(info.location),
        present_ids=[ids[p] for p in info.present if p in ids],
        recent_message_ids=[ids[turn_key(t)] for t in turns[:k]],
        reveal_refs=[ref(r.ref) for r in info.reveals],
        planned_npc_handles=[ref(p) for p in info.planned_npcs],
        open_disclosure_ids=[
            ids[d.handle]
            for d in info.open_disclosures
            if d.kind == NAME_DISCLOSURE and d.handle in ids
        ],
        protagonist_id=protagonist,
        companion_id=of_type(COMPANION),
        genre=scene.genre,
    )
