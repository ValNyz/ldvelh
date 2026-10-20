"""The resolver v2 of a turn, end to end (spec §4.5, §4.5.6): the candidates of the
narration, the decision cascade, then what it decided, applied in the turn's unit of work.

`decide` blocks and decides: reads and model calls only, so the caller runs it before
opening the turn's transaction (a model call never holds the source message's lock).
`apply` writes, inside that transaction:
- a NEW creates its entity through IdentityService.create_entity (`source` resolver), with
  the surface cleaned by code as its label (no leading article for a descriptor, the case
  kept); a verified trap (two entities under one descriptor) gets an internal suffix, an
  ambiguous label creates nothing (`create_ambiguous`);
- an ALIAS adds its surface as an alias of the linked entity; an introduction by a true
  name goes through the reveal table instead;
- every linked mention becomes entity_mentions rows (one per occurrence of its surface),
  and the message keeps the legacy narrator_context, [start, end, label, type] with the
  label the player may read (display_for_player), never the surface;
- the cascade's non-trivial decisions become identity_events.
Each write runs in its own savepoint: a failed one is counted and the rest applies.
Logs above DEBUG carry counts and ids only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from domain.identity import (
    DECISIONS,
    CandidateSet,
    EntityRef,
    MentionDecision,
    NewEntitySpec,
    SceneContext,
    SceneEntity,
    TurnDecisions,
    TurnRef,
    TurnResolution,
)
from kg.item_writes import write_item
from llm.session import LLMSession
from prompts.identity_prompt import format_handle
from repos import entities, messages
from services.identity.candidates import block
from services.identity.decision import decide_turn
from services.identity.mentions import mention_rows

logger = logging.getLogger(__name__)

MATCH, ALIAS, NEW, UNSURE, _ = DECISIONS
TRUE_NAME = "true_name"
PROTAGONIST = "protagonist"
DESCRIPTOR = "descriptor"
SOURCE = "resolver"
_LOG = "[IDENTITY] "
# Types whose entities the extractors enrich (the protagonist and the companion are
# linked, never changed by them, spec §4.10).
ENRICHABLE_TYPES = frozenset({"character", "location", "organization", "object"})


@dataclass(frozen=True)
class DecidedTurn:
    """The candidates of a turn's narration and what the cascade decided for it."""

    candidates: CandidateSet
    decisions: TurnDecisions


async def decide(
    identity, conn, session: LLMSession, narration: str, scene: SceneContext
) -> DecidedTurn:
    """Blocking (SQL) then the decision cascade (model calls): no write."""
    candidates = await block(
        conn,
        identity.game_id,
        narration,
        scene,
        config=identity.config,
        normalizer=identity.normalizer,
        lexicon=identity.lexicon,
    )
    decisions = await decide_turn(
        session,
        conn,
        narration,
        candidates,
        scene,
        thresholds=identity.config,
        normalizer=identity.normalizer,
        lexicon=identity.lexicon,
    )
    return DecidedTurn(candidates, decisions)


class _Application:
    """The writes of one turn's decisions, on the turn's connection."""

    def __init__(self, identity, conn, turn: TurnRef, scene: SceneContext):
        self.identity, self.conn, self.turn, self.scene = identity, conn, turn, scene
        self.errors: list[str | dict] = []
        self.created: dict[UUID, str] = {}  # new entity -> its type
        self.aliases_added = 0
        self.reveals = []

    async def link(
        self, decisions: list[MentionDecision]
    ) -> list[tuple[MentionDecision, UUID]]:
        """(decision, entity) of every mention that names an entity, NEW created."""
        linked = []
        made: dict[int, UUID | None] = {}
        for i, d in enumerate(decisions):
            if d.ignored:
                continue
            if d.decision in (MATCH, ALIAS) and d.entity_id is not None:
                linked.append((d, d.entity_id))
                if d.decision == ALIAS and d.alias_kind is not None:
                    await self._alias(d)
            elif d.decision == NEW:
                origin = made.get(d.same_as) if d.same_as is not None else None
                made[i] = origin if d.same_as is not None else await self._create(d)
                if made[i] is not None:
                    linked.append((d, made[i]))
        return linked

    async def _write(self, label: str, write):
        return await write_item(self.conn, self.errors, label, write, _LOG)

    async def _alias(self, d: MentionDecision) -> None:
        identity, conn, entity_id = self.identity, self.conn, d.entity_id
        if d.alias_kind == TRUE_NAME:
            registry = await entities.get_registry(conn, identity.game_id, entity_id)
            if registry is None:
                return
            outcome = await self._write(
                "resolver reveal",
                lambda: identity.reveal(
                    conn,
                    EntityRef(str(entity_id), registry.entity_type),
                    d.surface,
                    turn_id=self.turn.turn_id,
                    source=SOURCE,
                    evidence=d.evidence or None,
                ),
            )
            if outcome is not None:
                self.reveals.append(outcome)
            return
        added = await self._write(
            "resolver alias",
            lambda: identity.add_alias(
                conn,
                entity_id,
                d.surface,
                d.alias_kind,
                known=True,
                source=SOURCE,
                turn_id=self.turn.turn_id,
                evidence=d.evidence or None,
            ),
        )
        self.aliases_added += bool(added)

    def label_of(self, d: MentionDecision) -> str:
        """The label of a NEW: its surface, a descriptor without its leading article
        and with a capital first letter, a proper name as written."""
        if d.new_kind != DESCRIPTOR:
            return " ".join(d.surface.split())
        bare = self.identity.normalizer.strip_article(d.surface, self.identity.lexicon)
        return bare[:1].upper() + bare[1:]

    def _is_trap(self, d: MentionDecision, holders: set[UUID]) -> bool:
        """A verified second entity under a label live `holders` already hold (spec
        §4.6): the two talk to each other, or a descriptor whose holder is not in this
        scene."""
        if d.talks_to:
            return True
        return (
            d.new_kind == DESCRIPTOR
            and bool(holders)
            and not holders & set(self.scene.present_ids)
        )

    async def _create(self, d: MentionDecision) -> UUID | None:
        identity, conn = self.identity, self.conn
        label = self.label_of(d)
        if not label:
            return None
        before = set(
            await entities.live_candidates(conn, identity.game_id, label, d.new_type)
        )
        trap = self._is_trap(d, before)
        spec = NewEntitySpec(
            d.new_type,
            label,
            d.new_kind,
            known=True,
            # Stamped with the turn's cycle, like an extracted entity (#84).
            fields={"created_cycle": self.turn.cycle},
        )
        entity_id = await self._write(
            "resolver create",
            lambda: identity.create_entity(
                conn,
                spec,
                turn_id=self.turn.turn_id,
                source=SOURCE,
                scene_location_id=self.scene.location_id,
                trap=trap,
            ),
        )
        if entity_id is not None and entity_id not in before:
            self.created[entity_id] = d.new_type
        return entity_id


async def _narrator_context(conn, game_id: UUID, message_id: UUID) -> int:
    """The legacy annotations of the message from its stored mentions (labels as the
    player may read them, merges followed); the number of spans."""
    rows = (await entities.mentions_for_messages(conn, game_id, [message_id])).get(
        message_id, []
    )
    if rows:
        await messages.set_narrator_context(
            conn,
            message_id,
            [[m.start_pos, m.end_pos, m.label, m.entity_type] for m in rows],
        )
    return len(rows)


async def _scene_entities(
    conn,
    linked: list[tuple[MentionDecision, UUID]],
    scene: SceneContext,
    created: dict[UUID, str],
) -> list[tuple[UUID, SceneEntity]]:
    """The entities of the scene the extractors see, with their ids: those the turn
    names, those present and the place, never the protagonist (named PROTAGONIST)."""
    ids = [entity_id for _, entity_id in linked]
    ids += [*scene.present_ids, *([scene.location_id] if scene.location_id else [])]
    ids = [i for i in dict.fromkeys(ids) if i != scene.protagonist_id]
    return [
        (
            row.entity_id,
            SceneEntity(
                handle=format_handle(row.handle),
                entity_type=row.entity_type,
                label=row.label,
                known=row.known,
                is_new=row.entity_id in created,
            ),
        )
        for row in await entities.scene_entity_rows(conn, ids)
        if row.entity_type != PROTAGONIST
    ]


async def apply(
    identity,
    conn,
    turn: TurnRef,
    narration: str,
    scene: SceneContext,
    decided: DecidedTurn,
) -> TurnResolution:
    """Apply a turn's decisions (see the module docstring); returns what was done."""
    decisions = decided.decisions
    application = _Application(identity, conn, turn, scene)
    linked = await application.link(decisions.decisions)
    mentions = mention_rows(narration, linked, identity.normalizer)
    await entities.insert_mentions(
        conn, identity.game_id, turn.message_id, turn.turn_id, mentions
    )
    spans = await _narrator_context(conn, identity.game_id, turn.message_id)
    for kind, entity_id, payload in decisions.events():
        await identity.record_event(conn, kind, turn.turn_id, entity_id, payload)
    linked_ids = list(dict.fromkeys(entity_id for _, entity_id in linked))
    bare = await entities.bare_entities(conn, linked_ids)
    new_types = {
        t
        for t in [*application.created.values(), *bare.values()]
        if t in ENRICHABLE_TYPES
    }
    scene_entities = await _scene_entities(conn, linked, scene, application.created)
    logger.info(
        f"{_LOG}turn resolved game={identity.game_id} mentions={len(mentions)}"
        f" spans={spans} created={len(application.created)}"
        f" aliases={application.aliases_added} reveals={len(application.reveals)}"
        f" fallback={decisions.fallback} escalated={decisions.escalated}"
        f" errors={len(application.errors)}"
    )
    return TurnResolution(
        mentions=mentions,
        created=[(i, line) for i, line in scene_entities if line.is_new],
        aliases_added=application.aliases_added,
        reveals=application.reveals,
        scene_entities=[line for _, line in scene_entities],
        new_types=new_types,
        escalated=decisions.escalated,
        fallback=decisions.fallback,
        deterministic=sum(1 for d in decisions.decisions if d.deterministic),
        unsure=sum(1 for d in decisions.decisions if d.decision == UNSURE),
        usage=decisions.usage,
    )
