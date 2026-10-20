"""Reveals (spec §4.7): the protagonist learns an entity's name, or a fact.

A reveal names its entity by a typed reference (`find_entity`: handle, id, label or
alias, so a descriptor with or without its article finds its character), never by a
guess: an unresolved or ambiguous reference is a counted no-op. Then the table of §4.7,
row by row:

- no revealed name: the protagonist knows the true name the entity has; none: no-op;
- the revealed name designates another entity of the type (a character by a true name
  only, never a descriptor or a short form; another entity by its label): the two are
  merged into the older when the guards allow it (the survivor then goes through the
  table), else the refusal is counted and nothing is written, so the holder still
  resolves by its name;
- a form that another entity holds as its registry label without designating it (an
  unnamed character's descriptor) is still given below, with an internal label suffix
  (R14) so that the registry stays unique;
- no true name yet (a character known by its descriptor): it becomes the true name, the
  descriptor stays an alias;
- the same name (same norm, or similarity >= IdentityConfig.reveal_match): known, the
  narration's spelling an alias, the existing spelling kept;
- another name: the narration wins (the player read it), the old name becomes a former
  name, counted as a conflict.

Nothing is deleted: every write goes through the domain row's triggers and the aliases,
journaled under the turn, so undoing the turn restores the entity as it was. A reveal is
idempotent: applied twice, the second one finds nothing left to do and records no
event (the counted no-ops and refusals are recorded once per reveal and turn).
Locations, organizations and objects follow the same table (their "true name" is their
name, their knowledge the flags of its aliases); objects are never merged automatically.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from repos import entities
from services.identity import merges
from services.identity.aliases import derive
from services.identity.types import EntityRef, FactRef, RevealOutcome

if TYPE_CHECKING:
    from services.identity.service import IdentityService

logger = logging.getLogger(__name__)

CHARACTER = "character"
# Types a revealed name never merges automatically (spec §4.7: the resolver decides).
_NEVER_AUTO_MERGED = frozenset({"object"})


def _name_column(entity_type: str) -> str:
    return "true_name" if entity_type == CHARACTER else "name"


def _name_kind(entity_type: str) -> str:
    return "true_name" if entity_type == CHARACTER else "label"


async def reveal(
    service: IdentityService,
    conn,
    ref: EntityRef | FactRef,
    real_name: str | None,
    *,
    turn_id: UUID | None,
    source: str,
    evidence: str | None = None,
) -> RevealOutcome:
    if isinstance(ref, FactRef):
        return await _reveal_fact(service, conn, ref, turn_id)
    resolved = await service.resolve_ref(conn, ref.ref, ref.entity_type)
    if resolved is None:
        await _noop_event(
            service,
            conn,
            turn_id,
            None,
            ref.entity_type,
            "unresolved",
            ref_key=_ref_key(service, ref.ref),
        )
        return RevealOutcome("noop", None)
    entity_id = resolved.entity_id
    real = " ".join(real_name.split()) if real_name else ""
    step = _Reveal(service, conn, ref.entity_type, turn_id, source, evidence)
    if not real:
        outcome = await step.known(entity_id)
    elif holders := await entities.name_holders(
        conn, service.game_id, ref.entity_type, real, entity_id
    ):
        outcome = await step.other_entity(entity_id, holders, real)
    else:
        outcome = await step.named(entity_id, real)
    logger.info(
        f"[IDENTITY] reveal {outcome.kind} game={service.game_id} id={entity_id}"
        f" source={source}"
    )
    logger.debug(f"[IDENTITY] reveal of {ref.ref!r} as {real_name!r}")
    return outcome


async def _reveal_fact(
    service: IdentityService, conn, ref: FactRef, turn_id: UUID | None
) -> RevealOutcome:
    fact_id = await entities.find_fact(conn, service.game_id, ref.ref)
    if fact_id is None:
        await _noop_event(
            service,
            conn,
            turn_id,
            None,
            "fact",
            "unresolved",
            ref_key=_ref_key(service, ref.ref),
        )
        return RevealOutcome("noop", None)
    if not await entities.set_fact_known(conn, service.game_id, fact_id):
        return RevealOutcome("known_only", fact_id)
    await service.record_event(
        conn, "reveal_applied", turn_id, None, {"fact_id": str(fact_id)}
    )
    return RevealOutcome("applied", fact_id)


async def _noop_event(
    service: IdentityService,
    conn,
    turn_id: UUID | None,
    entity_id: UUID | None,
    target: str,
    reason: str,
    *,
    ref_key: str | None = None,
) -> None:
    """A counted no-op, once per reveal and turn (a reveal is applied twice per turn: at
    the commit, then by the extraction). An unresolved one has no entity: `ref_key` tells
    two of them apart."""
    payload = {"entity_type": target, "reason": reason}
    if ref_key is not None:
        payload["ref_key"] = ref_key
    await service.record_event(
        conn, "reveal_noop", turn_id, entity_id, payload, once=True
    )


def _ref_key(service: IdentityService, ref: str | None) -> str:
    """A hash of the normalised reference: tells reveals apart without story text."""
    return hashlib.sha256(service.normalizer.norm(ref or "").encode()).hexdigest()


class _Reveal:
    """One reveal of one entity type, row by row of the table."""

    def __init__(
        self,
        service: IdentityService,
        conn,
        entity_type: str,
        turn_id: UUID | None,
        source: str,
        evidence: str | None,
    ):
        self.service = service
        self.conn = conn
        self.entity_type = entity_type
        self.turn_id = turn_id
        self.source = source
        self.evidence = evidence

    async def _current_name(self, entity_id: UUID) -> str | None:
        row = await entities.domain_row(self.conn, self.entity_type, entity_id) or {}
        return row.get(_name_column(self.entity_type))

    async def _event(self, kind: str, entity_id: UUID, **payload) -> None:
        await self.service.record_event(
            self.conn,
            kind,
            self.turn_id,
            entity_id,
            {"entity_type": self.entity_type, "source": self.source, **payload},
        )

    async def _mark_known(self, entity_id: UUID, name: str) -> bool:
        """The protagonist knows `name`, the entity's name: the character's flag and the
        aliases derived from it. False when nothing changed."""
        changed = False
        if self.entity_type == CHARACTER:
            changed = await entities.set_character_known(
                self.conn, self.service.game_id, entity_id
            )
        forms = derive(
            name,
            kind=_name_kind(self.entity_type),
            known=True,
            normalizer=self.service.normalizer,
            lexicon=self.service.lexicon,
        )
        flipped = await entities.mark_forms_known(
            self.conn, entity_id, [form.text for form in forms]
        )
        return changed or flipped > 0

    async def known(self, entity_id: UUID) -> RevealOutcome:
        """No revealed name: the entity's own name becomes known, if it has one."""
        name = await self._current_name(entity_id)
        if not name:
            await _noop_event(
                self.service,
                self.conn,
                self.turn_id,
                entity_id,
                self.entity_type,
                "no_name",
            )
            return RevealOutcome("noop", entity_id)
        if await self._mark_known(entity_id, name):
            await self._event("reveal_applied", entity_id, case="known")
        return RevealOutcome("known_only", entity_id)

    async def named(self, entity_id: UUID, real: str) -> RevealOutcome:
        """The revealed name designates no other entity: set, matched or in conflict."""
        name = await self._current_name(entity_id)
        if not name:
            await self._rename(entity_id, real)
            await self._event("reveal_applied", entity_id, case="named")
            return RevealOutcome("applied", entity_id)
        if await self._same_name(name, real):
            changed = await self._mark_known(entity_id, name)
            added = await self.service.add_alias(
                self.conn,
                entity_id,
                real,
                _name_kind(self.entity_type),
                known=True,
                source=self.source,
                turn_id=self.turn_id,
                evidence=self.evidence,
                entity_type=self.entity_type,
            )
            if changed or added:
                await self._event("reveal_applied", entity_id, case="matched")
            return RevealOutcome("known_only", entity_id)
        await self._rename(entity_id, real)
        await self._event("reveal_conflict", entity_id)
        return RevealOutcome("conflict", entity_id)

    async def _same_name(self, name: str, real: str) -> bool:
        similarity = await entities.name_similarity(
            self.conn, self.service.game_id, name, real
        )
        return similarity >= self.service.config.reveal_match

    async def _rename(self, entity_id: UUID, real: str) -> None:
        """`real` becomes the entity's name, known: the old one stays an alias (a
        descriptor stays a descriptor, a replaced name becomes a former name). A name
        another entity holds as its registry label without designating it (an unnamed
        character's descriptor) is still given: the registry label gets an internal
        suffix (R19b), the player and the prompts read the bare name."""
        if self.entity_type == CHARACTER:
            # Known first: the aliases of the new name are made known.
            await entities.set_character_known(
                self.conn, self.service.game_id, entity_id
            )
        await self.service.update_entity(
            self.conn,
            entity_id,
            self.entity_type,
            {_name_column(self.entity_type): real},
            source=self.source,
            turn_id=self.turn_id,
            evidence=self.evidence,
            suffix_if_held=True,
        )
        await self._mark_known(entity_id, real)

    async def other_entity(
        self, entity_id: UUID, holders: list[UUID], real: str
    ) -> RevealOutcome:
        """The revealed name is another entity's: one entity under two records, merged
        into the older one (it carries the planned arcs), unless a guard refuses."""
        keep, drop = None, None
        if len(holders) > 1:
            refused = "ambiguous"
        elif self.entity_type in _NEVER_AUTO_MERGED:
            refused = "never_auto_merged"
        else:
            [other] = holders
            keep = await entities.oldest(self.conn, [entity_id, other])
            drop = other if keep == entity_id else entity_id
            refused = await merges.refusal(self.service, self.conn, keep, drop)
        if refused is None:
            # The guards just passed: the merge itself, without running them again.
            await merges.apply(
                self.service,
                self.conn,
                keep,
                drop,
                reason="reveal",
                evidence=self.evidence,
            )
            # The survivor holds both records' names, a true name among them (a
            # character is designated only by one): the table applies to it.
            await self.named(keep, real)
            return RevealOutcome("merged", entity_id, merged_into=keep)
        await self.service.record_event(
            self.conn,
            "merge_refused",
            self.turn_id,
            entity_id,
            {
                "entity_type": self.entity_type,
                "refused": refused,
                "holder_ids": sorted(str(h) for h in holders),
            },
            once=True,
        )
        # Not merged, and no alias: the name stays its holder's, which must still resolve
        # by it. The entity's own name becomes known when it is that one.
        name = await self._current_name(entity_id)
        if name and await self._same_name(name, real):
            await self._mark_known(entity_id, name)
        return RevealOutcome("merge_refused", entity_id)
