"""IdentityService: the one entry point that creates, names and references an entity
(spec §4.4, §4.6, §4.11).

No pool: every method runs on the caller's connection, inside its transaction (a turn's
unit of work), so a lookup always sees the writes of the turn so far. References are
resolved by SQL (`find_entity`: reserved PROTAGONIST/COMPANION, handle, id, labels and
aliases of one type), never by an LLM; an ambiguous one is None, never a pick.

Label collisions (§4.6, ruling R14): creating an entity whose label a live entity of the
type already holds returns that entity, unless the caller verified a trap (two distinct
entities under one descriptor); the newcomer then gets an internal label suffix, from the
scene location's name, else the first free number. An entity removed from the world is
never a creation target (R21): a label only removed entities hold creates a fresh live
entity, suffixed the same way. The suffix lives in the registry label
only: the domain name, display_for_player and every player-facing read stay bare.

Logs carry ids, handles, counts and event codes; references and names only at DEBUG.
"""

from __future__ import annotations

import logging
from uuid import UUID

from config import IdentityConfig, get_identity_config
from domain.identity import (
    NEW_ENTITY_TYPES,
    AliasSpec,
    AmbiguousLabel,
    CandidateSet,
    EntityRef,
    FactRef,
    IdentityWriteMiss,
    MergeOutcome,
    NewEntitySpec,
    RefUnresolved,
    ResolvedRef,
    RevealOutcome,
    SceneContext,
    TurnRef,
    TurnResolution,
)
from llm.session import LLMSession
from packs.loader import load_lang
from repos import entities
from repos.uow import current_turn_id
from services.identity import lexicon as lexicons
from schema.extraction import ProposedEntity
from services.identity import merges, proposals, resolution, reveals
from services.identity.aliases import derive
from services.identity.classify import extracted_character_names, free_suffix
from services.identity.normalize import Normalizer

logger = logging.getLogger(__name__)

CHARACTER = "character"
# Types the service creates; the protagonist and the companion are made by game creation.
CREATABLE_TYPES = frozenset(NEW_ENTITY_TYPES)
# Columns the service sets itself from the spec: never taken from spec.fields.
_KNOWN_FLAG = "known_by_protagonist"
_NAME_COLUMNS = frozenset({"name", "true_name", "descriptor", _KNOWN_FLAG})
# Columns a character's bare label comes from (true name first), another entity's.
_CHARACTER_NAMES = ("true_name", "descriptor")
_OTHER_NAMES = ("name",)
# Columns a creation that reuses the entity holding its label may fill (#87): only with a
# value that is not blank, never a name, a flag only a reveal sets, nor a boolean or a
# default a schema fills in for every listing.
_REFILLABLE = {
    CHARACTER: (
        "species",
        "description",
        "traits",
        "mood",
        "occupation",
        "workplace_id",
        "residence_id",
    ),
    "location": ("parent_id", "location_type", "sector", "description", "atmosphere"),
    "organization": ("org_type", "domain", "description", "headquarters_id"),
}
# Untyped references (fact participants, relation ends) are reported under this type.
ANY_TYPE = "any"


def _refill_values(entity_type: str, fields: dict) -> dict:
    """The refillable columns of `fields` whose value is not blank (NULL, a blank string,
    an empty list); strings are kept trimmed."""
    values = {}
    for column in _REFILLABLE.get(entity_type, ()):
        value = fields.get(column)
        if isinstance(value, str):
            value = value.strip() or None
        elif isinstance(value, (list, tuple)) and not value:
            value = None
        if value is not None:
            values[column] = value
    return values


class IdentityService:
    def __init__(
        self,
        game_id: UUID,
        *,
        lang: str,
        genre: str | None = None,
        config: IdentityConfig,
    ):
        self.game_id = game_id
        self.config = config
        self.normalizer = Normalizer(load_lang(lang), config)
        self.lexicon = lexicons.for_game(lang, genre)

    @classmethod
    async def for_game(cls, conn, game_id: UUID) -> IdentityService:
        """The service of a game, with the packs of its language and genre."""
        config = get_identity_config()
        lang, genre = await entities.game_language(conn, game_id)
        return cls(
            game_id, lang=lang or config.default_language, genre=genre, config=config
        )

    # --- creation -----------------------------------------------------------------------

    async def create_entity(
        self,
        conn,
        spec: NewEntitySpec,
        *,
        turn_id: UUID | None,
        source: str,
        scene_location_id: UUID | None = None,
        trap: bool = False,
        refill: bool = False,
        reuse_aliases: bool = True,
    ) -> UUID:
        """Create an entity with its derived aliases, or return the live entity of the type
        that already holds its label (event 'create_reused'). A removed entity is never
        reused nor refilled: a label only removed entities hold creates a fresh entity,
        with an internal label suffix when a removed one still holds the label as its
        registry label (event 'label_suffixed'). With `trap` (a verified
        second entity under that label), the newcomer gets an internal label suffix
        (event 'label_suffixed'). With `refill` (an extractor listing an entity again), a
        reused entity holding the label as its own takes the values of `spec.fields`
        that are not blank, in the columns a re-listing may fill (#87); one found through
        an alias, or whose label another entity's alias contests, is left untouched.
        Without `reuse_aliases` (a list of distinct entities, the world generation), only
        an entity holding the label itself is reused: a label that only aliases match
        creates the entity (event 'create_contested'), never a fold into another one.
        `turn_id` defaults to the transaction's turn.

        A label that only aliases of several entities hold creates nothing (without
        `trap`): AmbiguousLabel is raised, and no event is written here. `write_item`
        writes its durable `create_ambiguous` row after the rollback; a caller outside
        write_item must record it itself."""
        label = " ".join(spec.label.split())
        if spec.entity_type not in CREATABLE_TYPES or not label:
            raise ValueError(
                f"cannot create a {spec.entity_type!r} entity with this label"
            )
        if reserved := set(spec.fields) & _NAME_COLUMNS:
            raise ValueError(f"fields set by the service: {sorted(reserved)}")
        if spec.descriptor and (
            spec.entity_type != CHARACTER or spec.kind != "proper_name"
        ):
            raise ValueError("only a character named by its true name has a descriptor")
        turn_id = turn_id or await current_turn_id(conn)
        target = await self.live_target(
            conn,
            await entities.find_for_upsert(conn, self.game_id, label, spec.entity_type),
            label,
            spec.entity_type,
        )
        alias_only = not reuse_aliases and (
            target.ambiguous or (target.entity_id is not None and not target.by_label)
        )
        if target.entity_id is not None and not trap and not alias_only:
            if refill and target.by_label and not target.contested:
                values = _refill_values(spec.entity_type, spec.fields)
                if values:
                    await entities.fill_domain_row(
                        conn, self.game_id, spec.entity_type, target.entity_id, values
                    )
            await self.record_event(
                conn,
                "create_reused",
                turn_id,
                target.entity_id,
                {
                    "entity_type": spec.entity_type,
                    "contested": target.contested,
                    "source": source,
                },
            )
            return target.entity_id
        contested = target.entity_id is not None or target.ambiguous
        candidates = (
            await self.label_candidates(conn, label, spec.entity_type)
            if contested
            else 0
        )
        if target.ambiguous and not trap and not alias_only:
            # Dans le doute, on ne crée pas (spec §2): write_item counts it.
            raise AmbiguousLabel(
                label,
                spec.entity_type,
                self.game_id,
                candidates=candidates,
                source=source,
            )
        suffix, suffix_from = None, None
        # Held here only by a verified trap's homonym or by a removed entity.
        if await entities.label_taken(conn, self.game_id, spec.entity_type, label):
            suffix, suffix_from = await self._free_suffix(
                conn, spec.entity_type, label, scene_location_id
            )
        entity_id = await entities.insert_domain_row(
            conn,
            self.game_id,
            spec.entity_type,
            self._domain_values(spec, label),
            label_suffix=suffix,
        )
        if turn_id is not None:
            await entities.set_created_turn(conn, entity_id, turn_id)
        await self._add_creation_aliases(conn, entity_id, spec, label, source, turn_id)
        if suffix is not None:
            await self.record_event(
                conn,
                "label_suffixed",
                turn_id,
                entity_id,
                {"entity_type": spec.entity_type, "suffix_from": suffix_from},
            )
        elif contested:
            # A verified trap whose label is free but names others through their aliases.
            await self.record_event(
                conn,
                "create_contested",
                turn_id,
                entity_id,
                {
                    "entity_type": spec.entity_type,
                    "candidates": candidates,
                    "source": source,
                },
            )
        logger.info(
            f"[IDENTITY] {spec.entity_type} created game={self.game_id} id={entity_id}"
            f" source={source}"
        )
        return entity_id

    async def live_target(
        self, conn, target: entities.UpsertTarget, label: str, entity_type: str
    ) -> entities.UpsertTarget:
        """`target` restricted to live entities: one removed from the world is no target.
        When the name lands on a removed entity, or is ambiguous, the live entities
        holding it decide: one is the target (holding the label as its own bare name,
        or not), several are an ambiguity, none is a new entity."""
        if target.entity_id is None and not target.ambiguous:
            return target
        if target.entity_id is not None and await entities.is_live(
            conn, entity_type, target.entity_id
        ):
            return target
        live = await entities.live_candidates(conn, self.game_id, label, entity_type)
        if len(live) > 1:
            return entities.UpsertTarget(None, False, True)
        if not live:
            return entities.UpsertTarget(None, False, False)
        row = await entities.domain_row(conn, entity_type, live[0]) or {}
        names = _CHARACTER_NAMES if entity_type == CHARACTER else _OTHER_NAMES
        bare = next((row[n] for n in names if row.get(n)), None)
        own = bool(bare) and self.normalizer.norm(bare) == self.normalizer.norm(label)
        return entities.UpsertTarget(live[0], own, False)

    def _domain_values(self, spec: NewEntitySpec, label: str) -> dict:
        proper = spec.kind == "proper_name"
        if spec.entity_type == CHARACTER:
            names = (
                {"true_name": label, "known_by_protagonist": spec.known}
                if proper
                # No true name to know: a reveal sets both later.
                else {"descriptor": label, "known_by_protagonist": False}
            )
            if proper and spec.descriptor:
                names["descriptor"] = " ".join(spec.descriptor.split())
        else:
            names = {"name": label}
        return {**names, **spec.fields}

    async def _free_suffix(
        self,
        conn,
        entity_type: str,
        label: str,
        scene_location_id: UUID | None,
        *,
        exclude: UUID | None = None,
    ) -> tuple[str, str]:
        """(suffix, where it comes from): the scene location's name when the label it makes
        is free, else the first free homonym number (classify.free_suffix, ruling R9).
        `exclude`: an entity being renamed, whose own label takes nothing."""
        place = None
        if scene_location_id is not None:
            place = await entities.display_for_player(conn, scene_location_id)
        holders = await entities.label_holders(conn, self.game_id, entity_type, label)
        taken = {
            norm: ids - {exclude} for norm, ids in holders.items() if ids - {exclude}
        }
        suffix = free_suffix(label, place or None, taken, self.normalizer)
        return suffix, "scene_location" if place and suffix == place else "counter"

    async def label_candidates(self, conn, label: str, entity_type: str) -> int:
        """Live entities of the type whose label or alias has the label's normal form."""
        counts = await entities.candidate_counts(
            conn, self.game_id, label, (entity_type,)
        )
        return counts.get(entity_type, 0)

    async def _add_creation_aliases(
        self,
        conn,
        entity_id: UUID,
        spec: NewEntitySpec,
        label: str,
        source: str,
        turn_id: UUID | None,
    ) -> None:
        """The derived aliases and the spec's own; the triggers already made the aliases of
        the names (source 'system'), whose flags follow the spec."""
        if spec.kind == "descriptor":
            kind = "descriptor"
        else:
            kind = "true_name" if spec.entity_type == CHARACTER else "label"
        derived = derive(
            label,
            kind=kind,
            known=spec.known,
            secret=spec.secret,
            normalizer=self.normalizer,
            lexicon=self.lexicon,
        )
        # A character's name aliases already follow known_by_protagonist; another entity's
        # are known (its suffixed label aside, internal) unless the spec says otherwise.
        unknown = spec.entity_type != CHARACTER and not spec.known
        if unknown or spec.secret:
            await entities.mark_aliases(
                conn, entity_id, known=False if unknown else None, secret=spec.secret
            )
        for alias in [*derived, *spec.aliases]:
            await self.add_alias(
                conn,
                entity_id,
                alias.text,
                alias.kind,
                known=alias.known,
                secret=alias.secret or spec.secret,
                source=source,
                turn_id=turn_id,
                entity_type=spec.entity_type,
            )

    async def add_alias(
        self,
        conn,
        entity_id: UUID,
        alias: str,
        kind: str,
        *,
        known: bool,
        secret: bool = False,
        source: str,
        turn_id: UUID | None = None,
        evidence: str | None = None,
        entity_type: str | None = None,
    ) -> bool:
        """Add an alias to an entity; False when it already has one of that normal form."""
        if entity_type is None:
            registry = await entities.get_registry(conn, self.game_id, entity_id)
            if registry is None:
                raise IdentityWriteMiss("entity_registry", entity_id, self.game_id)
            entity_type = registry.entity_type
        return await entities.insert_alias(
            conn,
            self.game_id,
            entity_id,
            entity_type,
            alias,
            kind,
            known=known,
            secret=secret,
            source=source,
            turn_id=turn_id,
            evidence=evidence,
        )

    # --- references ---------------------------------------------------------------------

    async def resolve_ref(self, conn, ref: str, entity_type: str) -> ResolvedRef | None:
        """The entity of `entity_type` that `ref` names (exact: reserved word, handle, id,
        label or alias), None when none does or several do (event 'ambiguous_ref')."""
        resolved, _ = await self._resolve(conn, ref, entity_type)
        return resolved

    async def require_ref(self, conn, ref: str, entity_type: str) -> ResolvedRef:
        """`resolve_ref`, raising RefUnresolved instead of None (write_item counts it and
        writes its event after rolling back the item, 'ambiguous_ref' included)."""
        resolved, candidates = await self._resolve(conn, ref, entity_type)
        if resolved is None:
            raise RefUnresolved(ref, entity_type, self.game_id, candidates=candidates)
        return resolved

    async def _resolve(
        self, conn, ref: str, entity_type: str
    ) -> tuple[ResolvedRef | None, int]:
        """(the resolved entity, None when unresolved; the candidates of an unresolved
        reference: 0 unknown, 2 or more ambiguous)."""
        entity_id = await entities.find_entity(conn, self.game_id, ref, entity_type)
        if entity_id is not None:
            return await self.resolved_ref(conn, entity_id, entity_type), 1
        candidates = 0
        if ref and ref.strip():
            counts = await entities.candidate_counts(
                conn, self.game_id, ref, (entity_type,)
            )
            candidates = counts.get(entity_type, 0)
        return None, await self._unresolved(conn, ref, entity_type, candidates)

    async def resolve_live_ref(
        self, conn, ref: str, entity_type: str
    ) -> tuple[ResolvedRef | None, int]:
        """(the live entity of `entity_type` that `ref` names, None when none or several;
        the live candidates): a write target. An entity removed from the world never
        counts, and its name shared with a live homonym is no ambiguity: 'ambiguous_ref'
        is recorded only when two live entities or more match."""
        entity_id = await entities.find_entity(conn, self.game_id, ref, entity_type)
        if entity_id is not None and await entities.is_live(
            conn, entity_type, entity_id
        ):
            return await self.resolved_ref(conn, entity_id, entity_type), 1
        live = await entities.live_candidates(conn, self.game_id, ref, entity_type)
        if len(live) == 1:
            return await self.resolved_ref(conn, live[0], entity_type), 1
        return None, await self._unresolved(conn, ref, entity_type, len(live))

    async def require_live_ref(
        self, conn, ref: str, entity_type: str, *, or_removed: bool = False
    ) -> ResolvedRef:
        """`resolve_live_ref`, raising RefUnresolved instead of None, with the count of the
        removed entities `ref` names (`removed`: telemetry tells a removed entity from an
        unknown name). With `or_removed` (live first: an update, a removal, a reveal),
        a reference no live entity holds may still name one removed entity."""
        resolved, live = await self.resolve_live_ref(conn, ref, entity_type)
        if resolved is not None:
            return resolved
        hit = await entities.find_entity(conn, self.game_id, ref, entity_type)
        if or_removed and live == 0 and hit is not None:
            return await self.resolved_ref(conn, hit, entity_type)
        removed = 0
        if live == 0:
            removed = await entities.removed_candidates(
                conn, self.game_id, ref, entity_type
            )
            # A handle or an id of a removed entity is no label match.
            removed = max(removed, 1 if hit is not None else 0)
        raise RefUnresolved(
            ref, entity_type, self.game_id, candidates=live, removed=removed
        )

    async def require_any_live_ref(self, conn, ref: str) -> ResolvedRef:
        """The entity of any type that `ref` names (a fact participant, a relation end, an
        arc, event or chronology participant): only when exactly one type knows it, once
        (`find_any`), live first: the live entity a name designates is found even when a
        removed homonym shares the name, two live ones are ambiguous, and a name no live
        entity holds may still name one removed entity (a fact about a dead NPC).
        RefUnresolved (type 'any') otherwise, with `candidates` the live candidates and
        `removed` the removed ones."""
        found = await entities.find_any(conn, self.game_id, ref, live_first=True)
        if found is not None:
            entity_id, entity_type = found
            return await self.resolved_ref(conn, entity_id, entity_type)
        live = removed = 0
        if ref and ref.strip():
            types = entities.ANY_ENTITY_TYPES
            live = sum(
                (
                    await entities.candidate_counts(
                        conn, self.game_id, ref, types, live_only=True
                    )
                ).values()
            )
            if live == 0:
                every = await entities.candidate_counts(conn, self.game_id, ref, types)
                removed = sum(every.values())
        await self._unresolved(conn, ref, ANY_TYPE, live)
        raise RefUnresolved(
            ref, ANY_TYPE, self.game_id, candidates=live, removed=removed
        )

    async def resolved_ref(
        self, conn, entity_id: UUID, entity_type: str
    ) -> ResolvedRef:
        """The handle and the player-facing label of an entity of known id."""
        handle = await entities.handle_of(conn, entity_id)
        label = await entities.display_for_player(conn, entity_id)
        return ResolvedRef(entity_id, handle, label, entity_type)

    async def _unresolved(
        self, conn, ref: str, entity_type: str, candidates: int
    ) -> int:
        """Record an ambiguous reference ('ambiguous_ref', 2 or more candidates); returns
        `candidates`."""
        if candidates > 1:
            await self.record_event(
                conn,
                "ambiguous_ref",
                None,
                None,
                {"entity_type": entity_type, "candidates": candidates},
            )
        logger.debug(f"[IDENTITY] {entity_type} reference unresolved: {ref!r}")
        return candidates

    async def handles_for_prompt(self, conn, entity_ids: list[UUID]) -> dict[UUID, str]:
        """`E<n>` of each entity (its live one when merged), for the prompts."""
        return {
            entity_id: f"E{handle}"
            for entity_id, handle in (await entities.handles(conn, entity_ids)).items()
        }

    # --- writes by id -------------------------------------------------------------------

    async def update_entity(
        self,
        conn,
        entity_id: UUID,
        entity_type: str,
        fields: dict,
        *,
        source: str = "extractor",
        turn_id: UUID | None = None,
        evidence: str | None = None,
        suffix_if_held: bool = False,
    ) -> None:
        """Write `fields` on the entity's domain row, by id (merges followed). No row:
        IdentityWriteMiss. A new name keeps the old one as a former name (the triggers) and
        gets its derived aliases (a former name it takes back is its name again); an
        internal label suffix no homonym needs any more goes, in the same write. With
        `suffix_if_held`, a new name that another entity of the type holds as its
        registry label without being the same entity (an unnamed character's descriptor)
        gets an internal label suffix in the same write (R14, event 'label_suffixed'),
        never shown to the player. A bare label that does not change keeps its suffix.
        known_by_protagonist is the reveal's (explicit reveals only): refused here."""
        if _KNOWN_FLAG in fields:
            raise ValueError(f"{_KNOWN_FLAG} is written by a reveal, not update_entity")
        turn_id = turn_id or await current_turn_id(conn)
        live_id = await entities.follow_merge(conn, entity_id) or entity_id
        renamed = "true_name" if entity_type == CHARACTER else "name"
        suffix_change = await self._suffix_for_rename(
            conn, entity_type, live_id, fields, suffix_if_held
        )
        table, row = await entities.update_domain_row(
            conn,
            self.game_id,
            entity_type,
            live_id,
            fields,
            label_suffix=suffix_change,
        )
        if row is None:
            raise IdentityWriteMiss(table, entity_id, self.game_id)
        if suffix_change is not None and suffix_change.suffix is not None:
            await self.record_event(
                conn,
                "label_suffixed",
                turn_id,
                live_id,
                {"entity_type": entity_type, "suffix_from": suffix_change.origin},
            )
        if fields.get(renamed):
            known = entity_type != CHARACTER or bool(row.get("known_by_protagonist"))
            kind = "true_name" if entity_type == CHARACTER else "label"
            await entities.restore_former_name(conn, live_id, row[renamed], kind, known)
            for alias in derive(
                row[renamed],
                kind=kind,
                known=known,
                normalizer=self.normalizer,
                lexicon=self.lexicon,
            ):
                await self.add_alias(
                    conn,
                    live_id,
                    alias.text,
                    alias.kind,
                    known=alias.known,
                    secret=alias.secret,
                    source=source,
                    turn_id=turn_id,
                    evidence=evidence,
                    entity_type=entity_type,
                )

    async def _suffix_for_rename(
        self,
        conn,
        entity_type: str,
        entity_id: UUID,
        fields: dict,
        suffix_if_held: bool,
    ) -> entities.SuffixChange | None:
        """The label suffix a rename writes in the same statement as the name (None: left
        as it is). One write, so no alias of an intermediate label is ever made: a new
        bare label another entity holds gets a fresh suffix (with `suffix_if_held`), a
        free one drops the suffix the entity had."""
        names = _CHARACTER_NAMES if entity_type == CHARACTER else _OTHER_NAMES
        if not set(fields).intersection(names):
            return None
        current = await entities.domain_row(conn, entity_type, entity_id) or {}
        merged = {**current, **fields}
        bare = next((merged[n] for n in names if merged.get(n)), None)
        before = next((current[n] for n in names if current.get(n)), None)
        if not bare or (
            before and self.normalizer.norm(before) == self.normalizer.norm(bare)
        ):
            # The bare label does not change: nor does its suffix.
            return None
        if await entities.label_held_by_other(
            conn, self.game_id, entity_type, bare, entity_id
        ):
            if not suffix_if_held:
                return None
            suffix, origin = await self._free_suffix(
                conn, entity_type, bare, None, exclude=entity_id
            )
            return entities.SuffixChange(suffix, origin)
        if current.get("label_suffix"):
            return entities.SuffixChange(None, None)
        return None

    # --- the resolver v2 of a turn (spec §4.5) ------------------------------------------

    async def block(self, conn, narration: str, scene: SceneContext) -> CandidateSet:
        """The candidates of a narration (SQL, no model call). A turn is resolved in
        three steps, `block`, `decide` then `apply_resolution`, so that the caller holds
        no pool connection and no lock during the model calls (the extraction
        orchestrator's `resolve_phase`)."""
        return await resolution.block(self, conn, narration, scene)

    async def decide(
        self,
        reads,
        session: LLMSession,
        narration: str,
        scene: SceneContext,
        candidates: CandidateSet,
    ) -> resolution.DecidedTurn:
        """The decision cascade over the candidates: model calls, no write; `reads` (a
        connection or repos.pooled.PooledReads) only follows merges between calls."""
        return await resolution.decide(
            self, reads, session, narration, scene, candidates
        )

    async def apply_resolution(
        self,
        conn,
        turn: TurnRef,
        narration: str,
        scene: SceneContext,
        decided: resolution.DecidedTurn,
    ) -> TurnResolution:
        """Write what `decide` decided (stubs, aliases, reveals, mentions, events)."""
        return await resolution.apply(self, conn, turn, narration, scene, decided)

    # --- proposals of the extractors (spec §4.6, C6-C9) ---------------------------------

    async def create_from_extractor(
        self, conn, proposed: ProposedEntity, *, turn_id: UUID | None = None
    ) -> UUID:
        """The entity an extractor proposes, without a model call (the resolver should
        have seen it; a cost bound): the live entity a label or alias of the type names
        exactly (which takes the non-blank fields of the proposal when it holds the label,
        #87), else the one live entity of the type whose whole name is close
        (`proposals.close_entity`, event 'extractor_reused'; left untouched: its name is
        not the proposal's), else a new one (`create_entity`, source extractor). `proposed.fields` are columns of its row
        (references already ids). A character name that is not a proper name is a
        descriptor; next to a distinct descriptor it is a second descriptor, whose
        holder is reused when it already names a live character. Live entities only
        (R21), an internal suffix for a verified homonym (R14), and a label only
        aliases of several entities hold creates nothing (AmbiguousLabel, R16)."""
        turn_id = turn_id or await current_turn_id(conn)
        spec, extra = self._proposed_spec(proposed)
        if extra is not None and (
            reused := await self._reuse_by_name(conn, extra, turn_id)
        ):
            return reused
        target = await self.live_target(
            conn,
            await entities.find_for_upsert(
                conn, self.game_id, spec.label, spec.entity_type
            ),
            spec.label,
            spec.entity_type,
        )
        if target.entity_id is None and not target.ambiguous:
            similar = proposals.close_entity(
                spec.label,
                await entities.full_name_aliases(conn, self.game_id, spec.entity_type),
                threshold=self.config.create_from_extractor,
                normalizer=self.normalizer,
                lexicon=self.lexicon,
            )
            if similar is not None:
                await self.record_event(
                    conn,
                    "extractor_reused",
                    turn_id,
                    similar,
                    {"entity_type": spec.entity_type},
                )
                return similar
        return await self.create_entity(
            conn, spec, turn_id=turn_id, source="extractor", refill=True
        )

    def _proposed_spec(
        self, proposed: ProposedEntity
    ) -> tuple[NewEntitySpec, str | None]:
        """(the spec of a proposal, a character's second descriptor or None)."""
        entity_type = getattr(proposed.entity_type, "value", proposed.entity_type)
        label = " ".join(proposed.label.split())
        if entity_type != CHARACTER:
            return NewEntitySpec(
                entity_type, label, "proper_name", fields=dict(proposed.fields)
            ), None
        if proposed.kind == "descriptor":
            true_name, descriptor, extra = None, label, None
        else:
            true_name, descriptor, extra = extracted_character_names(
                label, proposed.descriptor, self.normalizer, self.lexicon
            )
        spec = NewEntitySpec(
            CHARACTER,
            true_name or descriptor,
            "proper_name" if true_name else "descriptor",
            known=proposed.known_by_protagonist,
            descriptor=descriptor if true_name else None,
            fields=dict(proposed.fields),
            aliases=[AliasSpec(extra, "descriptor", known=True)] if extra else [],
        )
        return spec, extra

    async def _reuse_by_name(
        self, conn, name: str, turn_id: UUID | None
    ) -> UUID | None:
        """The live character `name` already names (event 'create_reused' via name);
        AmbiguousLabel when several do; None when none does."""
        named = await self.live_target(
            conn,
            await entities.find_for_upsert(conn, self.game_id, name, CHARACTER),
            name,
            CHARACTER,
        )
        if named.ambiguous:
            raise AmbiguousLabel(
                name,
                CHARACTER,
                self.game_id,
                candidates=await self.label_candidates(conn, name, CHARACTER),
                source="extractor",
            )
        if named.entity_id is not None:
            await self.record_event(
                conn,
                "create_reused",
                turn_id,
                named.entity_id,
                {
                    "entity_type": CHARACTER,
                    "contested": named.contested,
                    "source": "extractor",
                    "via": "name",
                },
            )
        return named.entity_id

    # --- reveals and merges (spec §4.7) -------------------------------------------------

    async def reveal(
        self,
        conn,
        ref: EntityRef | FactRef,
        real_name: str | None,
        *,
        turn_id: UUID | None,
        source: str,
        evidence: str | None = None,
        disclosed: frozenset[UUID],
    ) -> RevealOutcome:
        """The protagonist learns the name of the entity `ref` names (`real_name`, else
        the name it has), or the fact: the table of spec §4.7 (`reveals`). Idempotent;
        an unresolved or ambiguous reference is a counted no-op, never a guess; a secret
        name of an entity not in `disclosed` is never revealed (`secret_closed`)."""
        return await reveals.reveal(
            self,
            conn,
            ref,
            real_name,
            turn_id=turn_id,
            source=source,
            evidence=evidence,
            disclosed=disclosed,
        )

    async def merge(
        self,
        conn,
        keep_id: UUID,
        drop_id: UUID,
        *,
        reason: str | None,
        turn_id: UUID | None,
        evidence: str | None = None,
    ) -> MergeOutcome:
        """Merge `drop_id` into `keep_id` when the guards allow it (`merges`): undoable
        through the turn's journal, audited in entity_merges."""
        return await merges.merge(
            self,
            conn,
            keep_id,
            drop_id,
            reason=reason,
            turn_id=turn_id,
            evidence=evidence,
        )

    # --- telemetry ----------------------------------------------------------------------

    async def record_event(
        self,
        conn,
        kind: str,
        turn_id: UUID | None,
        entity_id: UUID | None,
        payload: dict,
        *,
        once: bool = False,
    ) -> None:
        """An identity_events row (types, ids, counts, codes and hashes only). `once`: not
        again when the turn (else the transaction) already has the same event, kind,
        entity and payload (a reveal is applied at the commit and again by the extraction,
        in the same turn); a different payload is another event."""
        turn_id = turn_id or await current_turn_id(conn)
        if once and await entities.event_recorded(
            conn, self.game_id, kind, entity_id, turn_id, payload
        ):
            return
        await entities.insert_event(
            conn,
            self.game_id,
            kind,
            turn_id=turn_id,
            entity_id=entity_id,
            payload=payload,
        )
