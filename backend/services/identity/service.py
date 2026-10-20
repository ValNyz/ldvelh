"""IdentityService: the one entry point that creates, names and references an entity
(spec §4.4, §4.6, §4.11).

No pool: every method runs on the caller's connection, inside its transaction (a turn's
unit of work), so a lookup always sees the writes of the turn so far. References are
resolved by SQL (`find_entity`: reserved PROTAGONIST/COMPANION, handle, id, labels and
aliases of one type), never by an LLM; an ambiguous one is None, never a pick.

Label collisions (§4.6, ruling R14): creating an entity whose label a live entity of the
type already holds returns that entity, unless the caller verified a trap (two distinct
entities under one descriptor); the newcomer then gets an internal label suffix, from the
scene location's name, else the first free number. The suffix lives in the registry label
only: the domain name, display_for_player and every player-facing read stay bare.

Logs carry ids, handles, counts and event codes; references and names only at DEBUG.
"""

from __future__ import annotations

import logging
from itertools import count
from uuid import UUID

from config import IdentityConfig, get_identity_config
from packs.loader import load_lang
from repos import entities
from repos.uow import current_turn_id
from services.identity import lexicon as lexicons
from services.identity.aliases import derive
from services.identity.classify import label_of
from services.identity.normalize import Normalizer
from services.identity.types import (
    IdentityWriteMiss,
    NewEntitySpec,
    RefUnresolved,
    ResolvedRef,
)

logger = logging.getLogger(__name__)

CHARACTER = "character"
# Types the service creates; the protagonist and the companion are made by game creation.
CREATABLE_TYPES = frozenset({CHARACTER, "location", "organization", "object"})
# Columns the service sets itself from the spec: never taken from spec.fields.
_NAME_COLUMNS = frozenset({"name", "true_name", "descriptor", "known_by_protagonist"})
# Homonym counter (ruling R9): the first holder of a label keeps it bare, the n-th is (n).
_BARE_LABEL_RANK = 1


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
    ) -> UUID:
        """Create an entity with its derived aliases, or return the live entity of the type
        that already holds its label (event 'create_reused'). With `trap` (a verified
        second entity under that label), the newcomer gets an internal label suffix
        (event 'label_suffixed')."""
        label = " ".join(spec.label.split())
        if spec.entity_type not in CREATABLE_TYPES or not label:
            raise ValueError(
                f"cannot create a {spec.entity_type!r} entity with this label"
            )
        if reserved := set(spec.fields) & _NAME_COLUMNS:
            raise ValueError(f"fields set by the service: {sorted(reserved)}")
        target = await entities.find_for_upsert(
            conn, self.game_id, label, spec.entity_type
        )
        if target.entity_id is not None and not trap:
            await self._event(
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
        suffix, suffix_from = None, None
        if trap and await entities.label_taken(
            conn, self.game_id, spec.entity_type, label
        ):
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
            await self._event(
                conn,
                "label_suffixed",
                turn_id,
                entity_id,
                {"entity_type": spec.entity_type, "suffix_from": suffix_from},
            )
        logger.info(
            f"[IDENTITY] {spec.entity_type} created game={self.game_id} id={entity_id}"
            f" source={source}"
        )
        return entity_id

    def _domain_values(self, spec: NewEntitySpec, label: str) -> dict:
        proper = spec.kind == "proper_name"
        if spec.entity_type == CHARACTER:
            names = (
                {"true_name": label, "known_by_protagonist": spec.known}
                if proper
                # No true name to know: a reveal sets both later.
                else {"descriptor": label, "known_by_protagonist": False}
            )
        else:
            names = {"name": label}
        return {**names, **spec.fields}

    async def _free_suffix(
        self, conn, entity_type: str, label: str, scene_location_id: UUID | None
    ) -> tuple[str, str]:
        """(suffix, where it comes from): the scene location's name when the label it makes
        is free, else the first free homonym number (ruling R9)."""
        if scene_location_id is not None:
            place = await entities.display_for_player(conn, scene_location_id)
            if place and not await entities.label_taken(
                conn, self.game_id, entity_type, label_of(label, place)
            ):
                return place, "scene_location"
        for number in count(_BARE_LABEL_RANK + 1):
            suffix = str(number)
            if not await entities.label_taken(
                conn, self.game_id, entity_type, label_of(label, suffix)
            ):
                return suffix, "counter"
        raise AssertionError("unreachable")

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
        if spec.entity_type != CHARACTER or spec.secret:
            # A character's name aliases already follow known_by_protagonist.
            await entities.mark_aliases(
                conn,
                entity_id,
                known=None if spec.entity_type == CHARACTER else spec.known,
                secret=spec.secret,
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
            handle = await entities.handle_of(conn, entity_id)
            label = await entities.display_for_player(conn, entity_id)
            return ResolvedRef(entity_id, handle, label), 1
        candidates = 0
        if ref and ref.strip():
            counts = await entities.candidate_counts(
                conn, self.game_id, ref, (entity_type,)
            )
            candidates = counts.get(entity_type, 0)
        if candidates > 1:
            await self._event(
                conn,
                "ambiguous_ref",
                None,
                None,
                {"entity_type": entity_type, "candidates": candidates},
            )
        logger.debug(f"[IDENTITY] {entity_type} reference unresolved: {ref!r}")
        return None, candidates

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
    ) -> None:
        """Write `fields` on the entity's domain row, by id (merges followed). No row:
        IdentityWriteMiss. A new name keeps the old one as a former name (the triggers) and
        gets its derived aliases."""
        live_id = await entities.follow_merge(conn, entity_id) or entity_id
        table, row = await entities.update_domain_row(
            conn, self.game_id, entity_type, live_id, fields
        )
        if row is None:
            raise IdentityWriteMiss(table, entity_id, self.game_id)
        renamed = "true_name" if entity_type == CHARACTER else "name"
        if fields.get(renamed):
            known = entity_type != CHARACTER or bool(row.get("known_by_protagonist"))
            kind = "true_name" if entity_type == CHARACTER else "label"
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
                    entity_type=entity_type,
                )

    # --- telemetry ----------------------------------------------------------------------

    async def _event(
        self,
        conn,
        kind: str,
        turn_id: UUID | None,
        entity_id: UUID | None,
        payload: dict,
    ) -> None:
        await entities.insert_event(
            conn,
            self.game_id,
            kind,
            turn_id=turn_id or await current_turn_id(conn),
            entity_id=entity_id,
            payload=payload,
        )
