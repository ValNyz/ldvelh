"""The resolver v2 of a turn, end to end (spec §4.5, §4.5.6): the candidates of the
narration, the decision cascade, then what it decided, applied in the turn's unit of work.

`block` reads the candidates on a connection; `decide` runs the model cascade with only a
reader (`reads`: a connection, or repos.pooled.PooledReads that holds none between
statements), so the caller holds no pool connection and no lock during a model call.
`apply` writes, inside the turn's transaction:
- the decided links are checked again first: a merge committed meanwhile is followed, a
  link to an entity gone since the decision is dropped and counted (`link_stale`);
- a NEW creates its entity through IdentityService.create_entity (`source` resolver), with
  the surface cleaned by code as its label (no leading article for a descriptor, the case
  kept); a verified trap (two entities under one label) gets an internal suffix, an
  ambiguous label creates nothing (`create_ambiguous`);
- an ALIAS adds its surface as an alias of the linked entity; an introduction by a true
  name goes through the reveal table instead;
- every linked mention becomes entity_mentions rows (one per occurrence of its surface),
  and the message keeps the legacy narrator_context, [start, end, label, type] with the
  label the player may read (display_for_player), never the surface;
- the cascade's non-trivial decisions become identity_events;
- the entity types worth an extraction: the ones created, and the linked stubs without
  description named for the first time (so a stub the story never describes costs one
  extraction, not one per mention).
Each write runs in its own savepoint: a failed one is counted and the rest applies.
Logs above DEBUG carry counts and ids only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from uuid import UUID

from domain.identity import (
    DECISIONS,
    NEW_ENTITY_TYPES,
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
from services.identity import candidates as blocking
from services.identity.decision import decide_turn
from services.identity.mentions import mention_rows

logger = logging.getLogger(__name__)

MATCH, ALIAS, NEW, UNSURE, _ = DECISIONS
TRUE_NAME = "true_name"
PROTAGONIST = "protagonist"
DESCRIPTOR = "descriptor"
SOURCE = "resolver"
LINK_STALE = "link_stale"
_LOG = "[IDENTITY] "


@dataclass(frozen=True)
class DecidedTurn:
    """The candidates of a turn's narration and what the cascade decided for it."""

    candidates: CandidateSet
    decisions: TurnDecisions


async def block(identity, conn, narration: str, scene: SceneContext) -> CandidateSet:
    """The candidates of the narration (SQL, no model call)."""
    return await blocking.block(
        conn,
        identity.game_id,
        narration,
        scene,
        config=identity.config,
        normalizer=identity.normalizer,
        lexicon=identity.lexicon,
    )


async def decide(
    identity,
    reads,
    session: LLMSession,
    narration: str,
    scene: SceneContext,
    candidates: CandidateSet,
) -> DecidedTurn:
    """The decision cascade (model calls) over the turn's candidates: no write; `reads`
    only follows merges between the calls."""
    decisions = await decide_turn(
        session,
        reads,
        narration,
        candidates,
        scene,
        thresholds=identity.config,
        normalizer=identity.normalizer,
        lexicon=identity.lexicon,
    )
    return DecidedTurn(candidates, decisions)


def _links(d: MentionDecision) -> bool:
    return d.decision in (MATCH, ALIAS) and d.entity_id is not None and not d.ignored


class _Application:
    """The writes of one turn's decisions, on the turn's connection."""

    def __init__(self, identity, conn, turn: TurnRef, scene: SceneContext):
        self.identity, self.conn, self.turn, self.scene = identity, conn, turn, scene
        self.errors: list[str | dict] = []
        self.created: dict[UUID, str] = {}  # new entity -> its type
        self.aliases_added = 0
        self.stale = 0
        self.reveals = []

    async def current(self, decisions: list[MentionDecision]) -> list[MentionDecision]:
        """The decisions on the entities as they are now: a link to an entity merged
        since the decision moves to the one kept, a link to an entity gone is dropped
        (counted, event `link_stale`). An entity removed from the world stays linkable:
        the story may name the dead."""
        ids = [d.entity_id for d in decisions if _links(d) and d.entity_id]
        redirects = await entities.follow_merges(self.conn, ids)
        live = await entities.existing_entities(
            self.conn, self.identity.game_id, [redirects.get(i, i) for i in ids]
        )
        out = []
        for d in decisions:
            if not _links(d) or d.entity_id is None:
                out.append(d)
                continue
            now = redirects.get(d.entity_id, d.entity_id)
            if now not in live:
                self.stale += 1
                self.errors.append({"code": LINK_STALE, "item": "resolver link"})
                await self.identity.record_event(
                    self.conn,
                    LINK_STALE,
                    self.turn.turn_id,
                    None,
                    {"decision": d.decision},
                )
                out.append(replace(d, ignored=True))
            elif now != d.entity_id:
                out.append(replace(d, entity_id=now, redirected_from=d.entity_id))
            else:
                out.append(d)
        return out

    async def link(
        self, decisions: list[MentionDecision]
    ) -> list[tuple[MentionDecision, UUID]]:
        """(decision, entity) of every mention that names an entity, NEW created."""
        linked: list[tuple[MentionDecision, UUID]] = []
        made: dict[int, UUID | None] = {}
        for i, d in enumerate(decisions):
            if _links(d) and d.entity_id is not None:
                linked.append((d, d.entity_id))
                if d.decision == ALIAS and d.alias_kind is not None:
                    await self._alias(d, d.entity_id, d.alias_kind)
            elif d.decision == NEW and not d.ignored:
                if d.same_as is not None:
                    made[i] = made.get(d.same_as)
                elif d.new_type is not None and d.new_kind is not None:
                    made[i] = await self._create(d, d.new_type, d.new_kind)
                entity_id = made.get(i)
                if entity_id is not None:
                    linked.append((d, entity_id))
        return linked

    async def _write(self, label: str, write):
        return await write_item(self.conn, self.errors, label, write, _LOG)

    async def _alias(self, d: MentionDecision, entity_id: UUID, kind: str) -> None:
        identity, conn = self.identity, self.conn
        if kind == TRUE_NAME:
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
                kind,
                known=True,
                source=SOURCE,
                turn_id=self.turn.turn_id,
                evidence=d.evidence or None,
            ),
        )
        self.aliases_added += bool(added)

    def label_of(self, d: MentionDecision, kind: str) -> str:
        """The label of a NEW: its surface, a descriptor without its leading article
        and with a capital first letter, a proper name as written."""
        if kind != DESCRIPTOR:
            return " ".join(d.surface.split())
        bare = self.identity.normalizer.strip_article(d.surface, self.identity.lexicon)
        return bare[:1].upper() + bare[1:]

    async def _is_trap(self, d: MentionDecision, kind: str, holders: set[UUID]) -> bool:
        """A verified second entity under a label live `holders` already hold (spec
        §4.6): the two talk to each other, or a descriptor seen at a place other than
        every holder's known place (workplace, residence, frequented place). A holder
        whose place is unknown, or a scene without place, proves nothing: no trap."""
        if d.talks_to:
            return True
        here = self.scene.location_id
        if kind != DESCRIPTOR or not holders or here is None:
            return False
        places = await entities.known_places(self.conn, list(holders))
        return all(places.get(h) for h in holders) and not any(
            here in places[h] for h in holders
        )

    async def _create(self, d: MentionDecision, entity_type: str, kind: str):
        identity, conn = self.identity, self.conn
        label = self.label_of(d, kind)
        if not label:
            return None
        before = set(
            await entities.live_candidates(conn, identity.game_id, label, entity_type)
        )
        trap = await self._is_trap(d, kind, before)
        spec = NewEntitySpec(
            entity_type,
            label,
            "descriptor" if kind == DESCRIPTOR else "proper_name",
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
            self.created[entity_id] = entity_type
        return entity_id

    async def worth_extracting(self, linked_ids: list[UUID]) -> set[str]:
        """Types of the entities created, and of the linked stubs without description
        named for the first time (no mention in an earlier message): a stub the story
        never describes is sent to an extractor once, not at every mention."""
        bare = await entities.bare_entities(self.conn, linked_ids)
        seen = await entities.mentioned_elsewhere(
            self.conn, self.identity.game_id, list(bare), self.turn.message_id
        )
        return {
            entity_type
            for entity_id, entity_type in {**bare, **self.created}.items()
            if entity_type in NEW_ENTITY_TYPES
            and (entity_id in self.created or entity_id not in seen)
        }


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
    # The decisions as they stand now: a merge caught here is recorded like one caught
    # at decision time (tombstone_redirected).
    decisions = replace(
        decisions, decisions=await application.current(decisions.decisions)
    )
    linked = await application.link(decisions.decisions)
    mentions = mention_rows(narration, linked, identity.normalizer)
    await entities.insert_mentions(
        conn, identity.game_id, turn.message_id, turn.turn_id, mentions
    )
    spans = await _narrator_context(conn, identity.game_id, turn.message_id)
    for kind, entity_id, payload in decisions.events():
        await identity.record_event(conn, kind, turn.turn_id, entity_id, payload)
    new_types = await application.worth_extracting(
        list(dict.fromkeys(entity_id for _, entity_id in linked))
    )
    scene_entities = await _scene_entities(conn, linked, scene, application.created)
    logger.info(
        f"{_LOG}turn resolved game={identity.game_id} mentions={len(mentions)}"
        f" spans={spans} created={len(application.created)}"
        f" aliases={application.aliases_added} reveals={len(application.reveals)}"
        f" stale={application.stale} fallback={decisions.fallback}"
        f" escalated={decisions.escalated} errors={len(application.errors)}"
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
