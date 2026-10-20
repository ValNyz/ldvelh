"""
LDVELH - Specialized Populators (Dedicated Tables Architecture)
WorldPopulator: Initial world generation processing
ExtractionPopulator: the writes the extractors route here

Every entity is created by IdentityService.create_entity (spec §4.6, C1-C9) and every
reference made of words is resolved at the edge (kg.refs) before a write by id; an
unresolved one is counted (`ref_dropped`), never dropped silently nor guessed.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel

from domain.identity import (
    AliasSpec,
    AmbiguousLabel,
    EntityRef,
    NewEntitySpec,
    UpdateRefused,
)
from repos import entities as entity_repo
from repos.uow import current_turn_id
from schema import (
    PROTAGONIST_REF,
    CharacterData,
    EntityCreation,
    EntityType,
    EntityUpdate,
    FactData,
    FactParticipant,
    FactType,
    InventoryChange,
    LocationData,
    ObjectCreation,
    ObjectData,
    OrganizationData,
    is_protagonist_ref,
)
from schema.entity_changes import bound_changes
from services.identity.classify import extracted_character_names

from . import refs
from .item_writes import write_item
from .populator import KnowledgeGraphPopulator
from .semantic_keys import arrival_key, use_key

if TYPE_CHECKING:
    from asyncpg import Connection

    from services.identity.service import IdentityService

logger = logging.getLogger(__name__)

# Fields of a data model that are not columns of its domain row: names (the service sets
# them from the spec) and references (resolved into the *_id columns).
_NOT_COLUMNS = frozenset(
    {
        "name",
        "known_by_protagonist",
        "descriptor",
        "quantity",
        "workplace_ref",
        "residence_ref",
        "parent_location_ref",
        "headquarters_ref",
    }
)


def _columns(data: BaseModel, cycle: int, **ids: UUID | None) -> dict:
    """The domain row columns of an entity data model (its references given as ids)."""
    values = data.model_dump(exclude=_NOT_COLUMNS)
    values["details"] = values.get("details") or {}
    values["created_cycle"] = cycle
    return {**values, **ids}


def _named_spec(
    entity_type: EntityType, data: BaseModel, cycle: int, **ids: UUID | None
) -> NewEntitySpec:
    """A location, organization or object named by its proper name."""
    return NewEntitySpec(
        entity_type.value,
        data.name,
        "proper_name",
        fields=_columns(data, cycle, **ids),
    )


# =============================================================================
# WORLD GENERATION POPULATOR
# =============================================================================


class WorldPopulator(KnowledgeGraphPopulator):
    """
    Populates the entire game world from a WorldGeneration output: every entity through
    IdentityService.create_entity (true name, descriptor, derived aliases), then the
    references (parents, headquarters, relations, arcs) resolved to ids.

    The lists of a generated world name distinct entities: an entity is reused only on
    its exact label (never through another one's derived alias), and a reference that is
    the exact label of an entity this world made is linked to that id (`_made`) before
    any lookup by alias.
    """

    async def populate(
        self,
        world_gen,
        user_id: UUID | None = None,
        finalize: Callable[[Connection], Awaitable[None]] | None = None,
        conn: Connection | None = None,
    ) -> UUID:
        """Main entry point — creates game and populates everything.

        `finalize(conn)` runs last, in the same transaction (the caller's own writes).
        `conn`: a connection the caller already holds (and releases), else one from the pool.
        """
        if conn is not None:
            return await self._populate_in(conn, world_gen, user_id, finalize)
        async with self.pool.acquire() as own_conn:
            return await self._populate_in(own_conn, world_gen, user_id, finalize)

    async def _populate_in(
        self,
        conn: Connection,
        world_gen,
        user_id: UUID | None,
        finalize: Callable[[Connection], Awaitable[None]] | None,
    ) -> UUID:
        """The whole world in one transaction on `conn`. A world item that cannot be
        written (an unresolved reference, an ambiguous label) is rolled back alone and
        counted in the generation's extraction log."""
        errors: list[str | dict] = []
        # (entity type, normalised label) -> id of each entity this world made.
        self._made: dict[tuple[str, str], UUID] = {}
        location = EntityType.LOCATION.value
        async with conn.transaction():
            # 1. Create game or rename existing
            if self.game_id:
                await self.rename_game(conn, world_gen.world.name)
            else:
                await self.create_game(conn, world_gen.world.name, user_id)

            # 2. Store world metadata on games table
            await self.set_world_data(
                conn,
                world_gen.world,
                seed_words=world_gen.generation_seed_words,
            )

            # 3. The station: the root location
            await self._create(conn, errors, self._station_spec(world_gen.world))

            # 4-5. Protagonist and companion (registered by their triggers)
            await self.create_protagonist(conn, world_gen.protagonist)
            await self.create_companion(conn, world_gen.companion)

            # 6-7. Organizations and locations (their references resolved below)
            for org in world_gen.organizations:
                await self._create(
                    conn, errors, _named_spec(EntityType.ORGANIZATION, org, 1)
                )
            for loc in world_gen.locations:
                await self._create(
                    conn, errors, _named_spec(EntityType.LOCATION, loc, 1)
                )

            # 8. References between them, now that they all exist
            await self._link(conn, errors, world_gen)

            # 9. Characters, with their workplace and residence
            for char in world_gen.characters:
                await self._create(
                    conn, errors, await self._character_spec(conn, errors, char)
                )

            # 10. Objects and the initial inventory
            for obj in world_gen.inventory:
                obj_id = await self._create(
                    conn, errors, _named_spec(EntityType.OBJECT, obj, 1)
                )
                if obj_id:
                    await self.add_to_inventory(
                        conn, obj_id, quantity=obj.quantity, cycle=1, origin="initial"
                    )

            # 11. Explicit relations (both ends required)
            for rel in world_gen.initial_relations:
                await write_item(
                    conn,
                    errors,
                    "relation",
                    lambda rel=rel: self._relation(conn, rel),
                    "[POPULATE] ",
                )

            # 12. Narrative arcs
            for arc in world_gen.narrative_arcs:
                participant_ids = []
                for ref in arc.involved_entities:
                    entity_id = await self._ref(conn, errors, "arc participant", ref)
                    if entity_id is not None and entity_id not in participant_ids:
                        participant_ids.append(entity_id)
                await self.create_narrative_arc(
                    conn, arc, cycle=1, participant_ids=participant_ids
                )

            # 13. Arrival event and initial game state
            arrival_loc_id = await self._ref(
                conn,
                errors,
                "arrival location",
                world_gen.arrival_event.arrival_location_ref,
                location,
            )
            await self._store_arrival_event(
                conn, world_gen.arrival_event, arrival_loc_id
            )
            await self.update_game_state(
                conn,
                cycle=1,
                date=world_gen.arrival_event.arrival_date,
                time=world_gen.arrival_event.time,
                location_id=arrival_loc_id,
            )

            # 14. Metadata
            entities = await self._store_generation_meta(conn, world_gen, errors)

            # 15. Caller's writes (engine, character, duration): all or nothing
            if finalize is not None:
                await finalize(conn)

            logger.info(f"World populated: {entities} entities, {len(errors)} errors")

        return self.game_id

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _create(
        self, conn: Connection, errors: list, spec: NewEntitySpec
    ) -> UUID | None:
        """One world entity through the identity service, in its own savepoint; reused
        only on its exact label (`reuse_aliases=False`)."""
        identity = await self.identity(conn)
        entity_id = await write_item(
            conn,
            errors,
            spec.entity_type,
            lambda: identity.create_entity(
                conn, spec, turn_id=None, source="world_gen", reuse_aliases=False
            ),
            "[POPULATE] ",
        )
        if entity_id is not None:
            key = (spec.entity_type, identity.normalizer.norm(spec.label))
            self._made.setdefault(key, entity_id)
        return entity_id

    def _made_id(self, ref: str | None, entity_type: str | None) -> UUID | None:
        """The entity of this world whose exact label is `ref` (of `entity_type`, or of
        any type when exactly one holds it)."""
        if not ref or self._identity is None:
            return None
        norm = self._identity.normalizer.norm(ref)
        hits = {
            entity_id
            for (made_type, made_norm), entity_id in self._made.items()
            if made_norm == norm and entity_type in (None, made_type)
        }
        return hits.pop() if len(hits) == 1 else None

    async def _ref(
        self,
        conn: Connection,
        errors: list,
        label: str,
        ref: str | None,
        entity_type: str | None = None,
    ) -> UUID | None:
        """`refs.optional`, after the entities this world made (exact label)."""
        made = self._made_id(ref, entity_type)
        if made is not None:
            return made
        identity = await self.identity(conn)
        return await refs.optional(
            identity,
            conn,
            errors,
            label,
            ref,
            entity_type,
            live=entity_type is not None,
        )

    async def _required_ref(self, conn: Connection, ref: str) -> UUID:
        """`refs.required` (untyped), after the entities this world made."""
        made = self._made_id(ref, None)
        if made is not None:
            return made
        return await refs.required(await self.identity(conn), conn, ref)

    @staticmethod
    def _station_spec(world) -> NewEntitySpec:
        station = LocationData(
            name=world.name,
            location_type="station",
            description=world.description,
            atmosphere=world.atmosphere,
            notable_features=world.sectors if hasattr(world, "sectors") else [],
        )
        return _named_spec(EntityType.LOCATION, station, 1)

    async def _character_spec(
        self, conn: Connection, errors: list, char
    ) -> NewEntitySpec:
        """A generated character: its name is its true name, next to its descriptor."""
        location = EntityType.LOCATION.value
        workplace_id = await self._ref(
            conn, errors, "character workplace", char.workplace_ref, location
        )
        residence_id = await self._ref(
            conn, errors, "character residence", char.residence_ref, location
        )
        return NewEntitySpec(
            EntityType.CHARACTER.value,
            char.name,
            "proper_name",
            known=char.known_by_protagonist,
            descriptor=char.descriptor,
            fields=_columns(
                char, 1, workplace_id=workplace_id, residence_id=residence_id
            ),
        )

    async def _link(self, conn: Connection, errors: list, world_gen) -> None:
        """Location parents, organization headquarters and the protagonist's employer
        and residence, linked by id."""
        location = EntityType.LOCATION.value
        for loc in world_gen.locations:
            await self._set_reference(
                conn,
                errors,
                EntityType.LOCATION,
                loc.name,
                "parent_id",
                loc.parent_location_ref,
            )
        for org in world_gen.organizations:
            await self._set_reference(
                conn,
                errors,
                EntityType.ORGANIZATION,
                org.name,
                "headquarters_id",
                org.headquarters_ref,
            )
        protagonist = world_gen.protagonist
        employer_id = await self._ref(
            conn,
            errors,
            "protagonist employer",
            protagonist.employer_ref,
            EntityType.ORGANIZATION.value,
        )
        residence_id = await self._ref(
            conn, errors, "protagonist residence", protagonist.residence_ref, location
        )
        await conn.execute(
            """UPDATE protagonists
               SET employer_id = COALESCE($2, employer_id),
                   residence_id = COALESCE($3, residence_id)
               WHERE game_id = $1 AND ($2::uuid IS NOT NULL OR $3::uuid IS NOT NULL)""",
            self.game_id,
            employer_id,
            residence_id,
        )

    async def _set_reference(
        self,
        conn: Connection,
        errors: list,
        entity_type: EntityType,
        name: str,
        column: str,
        ref: str | None,
    ) -> None:
        """Point `column` of the entity this world made as `name` at the location `ref`
        names."""
        entity_id = self._made_id(name, entity_type.value)
        if not ref or entity_id is None:
            return
        label = f"{entity_type.value} {column}"
        target_id = await self._ref(conn, errors, label, ref, EntityType.LOCATION.value)
        if target_id is None:
            return
        identity = await self.identity(conn)
        await write_item(
            conn,
            errors,
            label,
            lambda: identity.update_entity(
                conn,
                entity_id,
                entity_type.value,
                {column: target_id},
                source="world_gen",
            ),
            "[POPULATE] ",
        )

    async def _relation(self, conn: Connection, rel) -> UUID:
        return await self.create_relation(
            conn,
            await self._required_ref(conn, rel.source_ref),
            await self._required_ref(conn, rel.target_ref),
            rel.relation_type,
            level=rel.level,
            context=rel.context,
            known_by_protagonist=rel.known_by_protagonist,
        )

    async def _store_arrival_event(
        self, conn: Connection, arrival, location_id: UUID | None
    ) -> None:
        """Store arrival as facts + event + chronology entry."""
        protagonist_id = await self.protagonist_id(conn)
        actor = [(protagonist_id, "actor")] if protagonist_id else []
        time = getattr(arrival, "time", None)

        async def fact(fact_type, description, key, importance, participants, at=None):
            await self.create_fact(
                conn,
                FactData(
                    cycle=1,
                    fact_type=fact_type,
                    description=description,
                    time=time if at else None,
                    importance=importance,
                    semantic_key=arrival_key(key),
                ),
                participants,
                at,
            )

        # 1. Main arrival fact
        await fact(
            FactType.ENCOUNTER,
            f"Arrivée sur la station via {arrival.arrival_method}",
            "station",
            4,
            actor,
            location_id,
        )

        # 2. Milestone event, with the protagonist
        event_id = await self.create_event(
            conn,
            event_type="milestone",
            title="Arrivée sur la station",
            planned_cycle=1,
            description=f"Arrivée via {arrival.arrival_method}",
            time=time,
            location_id=location_id,
            completed=True,
        )
        if protagonist_id:
            await self.add_event_participant(conn, event_id, protagonist_id)

        # 3. Additional facts
        sensory = getattr(arrival, "immediate_sensory_details", None)
        if sensory:
            sensory_text = ". ".join(sensory) if isinstance(sensory, list) else sensory
            await fact(
                FactType.ATMOSPHERE,
                f"Premières impressions : {sensory_text[:250]}",
                "sensory",
                2,
                [],
                location_id,
            )
        incident = getattr(arrival, "optional_incident", None)
        if incident:
            await fact(
                FactType.ACTION, incident[:300], "incident", 3, actor, location_id
            )
        mood = getattr(arrival, "initial_mood", None)
        if mood:
            await fact(
                FactType.STATE_CHANGE, f"État à l'arrivée : {mood}", "mood", 2, actor
            )
        need = getattr(arrival, "immediate_need", None)
        if need:
            await fact(
                FactType.OBSERVATION, f"Besoin immédiat : {need}", "need", 2, actor
            )

        # 4. Chronology entry (replaces old cycle_summary)
        await self.save_chronology_entry(
            conn,
            cycle=0,
            summary=arrival.build_arrival_summary(),
            time=time,
            location_id=location_id,
        )

    async def _store_generation_meta(
        self, conn: Connection, world_gen, errors: list
    ) -> int:
        """Store generation metadata; returns the number of entities registered."""
        await self.update_game_timestamp(conn)
        entities = await entity_repo.live_entity_count(conn, self.game_id)
        await self.log_extraction(
            conn,
            cycle=0,
            stats={
                "entities_created": entities,
                "relations_created": len(world_gen.initial_relations),
                "errors": errors,
            },
        )
        return entities


# =============================================================================
# NARRATIVE EXTRACTION POPULATOR
# =============================================================================


class ExtractionPopulator(KnowledgeGraphPopulator):
    """
    The writes of the extractors (services/extraction): creations through the identity
    service, updates, inventory, facts and events by id, each reference resolved first.
    """

    # =========================================================================
    # ENTITY CREATION
    # =========================================================================

    async def create_extracted_entity(
        self, conn: Connection, errors: list, creation: EntityCreation, cycle: int
    ) -> UUID | None:
        """Create (or reuse) the entity an extractor lists in entities_created, through
        IdentityService.create_entity. A reused entity holding the label takes the
        non-blank fields (#87); an object is never put in the inventory here, only
        `acquired` does that (F18). None when nothing was written."""
        et = creation.entity_type
        if is_protagonist_ref(creation.name):
            logger.warning(
                f"[EXTRACT] Skipping a {et} named after the reserved reference (#28)"
            )
            return None
        identity = await self.identity(conn)
        data = creation.data or {}
        if et == EntityType.CHARACTER:
            return await self._create_character(conn, errors, identity, creation, cycle)
        if et == EntityType.LOCATION:
            spec = _named_spec(
                et,
                LocationData(name=creation.name, **data),
                cycle,
                parent_id=await refs.optional(
                    identity,
                    conn,
                    errors,
                    "create parent",
                    data.get("parent_location_ref"),
                    EntityType.LOCATION.value,
                    live=True,
                ),
            )
        elif et == EntityType.ORGANIZATION:
            spec = _named_spec(
                et,
                OrganizationData(name=creation.name, **data),
                cycle,
                headquarters_id=await refs.optional(
                    identity,
                    conn,
                    errors,
                    "create headquarters",
                    data.get("headquarters_ref"),
                    EntityType.LOCATION.value,
                    live=True,
                ),
            )
        elif et == EntityType.OBJECT:
            spec = _named_spec(et, ObjectData(name=creation.name, **data), cycle)
        else:
            # The name is story text (#77): only the type is logged.
            logger.warning(f"[EXTRACT] Unsupported entity type: {et}, creation skipped")
            return None
        return await self._extracted(conn, identity, spec)

    async def _create_character(
        self,
        conn: Connection,
        errors: list,
        identity: IdentityService,
        creation: EntityCreation,
        cycle: int,
    ) -> UUID:
        data = creation.data or {}
        location = EntityType.LOCATION.value
        char = CharacterData(
            name=creation.name,
            known_by_protagonist=creation.known_by_protagonist,
            descriptor=creation.descriptor,
            **{k: v for k, v in data.items() if k not in _NOT_COLUMNS},
        )
        fields = _columns(
            char,
            cycle,
            workplace_id=await refs.optional(
                identity,
                conn,
                errors,
                "create workplace",
                data.get("workplace_ref"),
                location,
                live=True,
            ),
            residence_id=await refs.optional(
                identity,
                conn,
                errors,
                "create residence",
                data.get("residence_ref"),
                location,
                live=True,
            ),
        )
        true_name, descriptor, extra = extracted_character_names(
            char.name, char.descriptor, identity.normalizer, identity.lexicon
        )
        if extra is not None:
            # The label is the descriptor; the extractor's own name must not name
            # another character already (the old upsert matched it first).
            # A removed character is no target (I1): the live ones decide.
            named = await identity.live_target(
                conn,
                await entity_repo.find_for_upsert(
                    conn, self.game_id, extra, EntityType.CHARACTER.value
                ),
                extra,
                EntityType.CHARACTER.value,
            )
            if named.ambiguous:
                raise AmbiguousLabel(
                    extra,
                    EntityType.CHARACTER.value,
                    self.game_id,
                    candidates=await identity.label_candidates(
                        conn, extra, EntityType.CHARACTER.value
                    ),
                    source="extractor",
                )
            if named.entity_id is not None:
                await identity.record_event(
                    conn,
                    "create_reused",
                    await _turn_of(conn),
                    named.entity_id,
                    {
                        "entity_type": EntityType.CHARACTER.value,
                        "contested": named.contested,
                        "source": "extractor",
                        "via": "name",
                    },
                )
                return named.entity_id
        spec = NewEntitySpec(
            EntityType.CHARACTER.value,
            true_name or descriptor,
            "proper_name" if true_name else "descriptor",
            known=char.known_by_protagonist,
            descriptor=descriptor if true_name else None,
            fields=fields,
            aliases=[AliasSpec(extra, "descriptor", known=True)] if extra else [],
        )
        return await self._extracted(conn, identity, spec)

    async def _extracted(
        self, conn: Connection, identity: IdentityService, spec: NewEntitySpec
    ) -> UUID:
        return await identity.create_entity(
            conn,
            spec,
            turn_id=await _turn_of(conn),
            source="extractor",
            refill=True,
        )

    async def create_object_by_label(
        self, conn: Connection, obj_creation: ObjectCreation, cycle: int
    ) -> UUID | None:
        """Create an acquired object (or reuse the one its name resolves to) and add it
        to the protagonist's inventory. None when nothing was added (a removed object)."""
        obj_data = ObjectData(
            name=obj_creation.name,
            category=obj_creation.category,
            description=obj_creation.description,
            transportable=obj_creation.transportable,
            stackable=obj_creation.stackable,
            base_value=obj_creation.base_value,
        )
        identity = await self.identity(conn)
        obj_id = await self._extracted(
            conn, identity, _named_spec(EntityType.OBJECT, obj_data, cycle)
        )
        if not await self.is_live(conn, EntityType.OBJECT, obj_id):
            return None
        await self.add_to_inventory(
            conn,
            obj_id,
            quantity=obj_creation.quantity,
            cycle=cycle,
            origin="acquired",
        )
        return obj_id

    # =========================================================================
    # ENTITY UPDATE ROUTING
    # =========================================================================

    async def _process_entity_update(
        self, conn: Connection, errors: list, update: EntityUpdate, cycle: int
    ) -> None:
        """Apply an extracted update to the entity its reference names, live first (the
        live homonym of a removed entity is reached by its name; RefUnresolved when none
        or several do, counted by the caller's savepoint).
        Extractors never update the companion, nor the protagonist beyond its skills
        (spec §4.10): the refused part is counted (`update_refused`), the skills of a
        protagonist update are still applied."""
        identity = await self.identity(conn)
        entity_type = update.entity_type
        resolved = await refs.resolve(
            identity,
            conn,
            update.entity_ref,
            entity_type and entity_type.value,
            live_first=True,
        )
        reserved = resolved.entity_type or entity_type.value
        if reserved == "companion" or (
            reserved == EntityType.PROTAGONIST.value and not update.skills_changed
        ):
            raise UpdateRefused(reserved)
        if reserved == EntityType.PROTAGONIST.value:
            if update.changes or update.removed or update.now_known:
                await _count_refusal(identity, conn, errors, resolved.entity_id)
            await self._update_entity_skills(
                conn,
                EntityType.PROTAGONIST,
                resolved.entity_id,
                update.skills_changed,
                cycle,
            )
            return
        changes = dict(update.changes)
        entity_type = entity_type or EntityType(resolved.entity_type)
        # Only an explicit reveal changes what the protagonist knows: a known flag among
        # the changes is one (without a name), never a demotion. The flag is read as its
        # column coerces it: a string such as "false" is not a reveal.
        flag = bound_changes(
            EntityType.CHARACTER,
            {"known_by_protagonist": changes.pop("known_by_protagonist", None)},
        ).get("known_by_protagonist")
        now_known = update.now_known is True or flag is True

        if now_known and entity_type == EntityType.CHARACTER:
            await identity.reveal(
                conn,
                EntityRef(str(resolved.entity_id), EntityType.CHARACTER.value),
                update.real_name,
                turn_id=None,
                source="extractor",
            )
        if changes:
            await self.update_entity(conn, resolved.entity_id, entity_type, changes)
        if update.skills_changed:
            await self._update_entity_skills(
                conn, entity_type, resolved.entity_id, update.skills_changed, cycle
            )
        if update.removed:
            await self.remove_extracted_entity(
                conn, resolved.entity_id, entity_type, cycle
            )

    async def remove_extracted_entity(
        self, conn: Connection, entity_id: UUID, entity_type: EntityType, cycle: int
    ) -> bool:
        """Mark an entity as removed, by id; one already removed is a counted no-op
        (event 'remove_noop'), not an error."""
        if await self.remove_entity(conn, entity_id, entity_type, cycle):
            return True
        identity = await self.identity(conn)
        await identity.record_event(
            conn,
            "remove_noop",
            None,
            entity_id,
            {"entity_type": entity_type.value},
        )
        return False

    async def _update_entity_skills(
        self,
        conn: Connection,
        entity_type: EntityType,
        entity_id: UUID,
        skills: list,
        cycle: int,
    ) -> None:
        """Update skills for a character or the protagonist, by id."""
        if entity_type == EntityType.CHARACTER:
            for skill in skills:
                await self.update_skill(conn, skill, cycle, character_id=entity_id)
        elif entity_type == EntityType.PROTAGONIST:
            for skill in skills:
                await self.update_skill(conn, skill, cycle, protagonist_id=entity_id)

    # =========================================================================
    # INVENTORY CHANGES
    # =========================================================================

    async def _process_inventory_change(
        self, conn: Connection, change: InventoryChange, cycle: int
    ) -> None:
        """Process acquire/lose/use inventory actions; the object is named by a
        reference that must resolve (RefUnresolved otherwise)."""
        identity = await self.identity(conn)
        obj = EntityType.OBJECT.value
        if change.action == "acquire":
            if change.object_hint or not change.object_ref:
                return  # A new object: objects_created writes it
            await self.add_to_inventory(
                conn,
                await refs.required(identity, conn, change.object_ref, obj, live=True),
                quantity=change.quantity_delta,
                cycle=cycle,
                origin="acquired",
            )
        elif change.action == "lose" and change.object_ref:
            await self.remove_from_inventory(
                conn,
                await refs.required(identity, conn, change.object_ref, obj, live=True),
                change.quantity_delta,
            )
        elif change.action == "use" and change.object_ref:
            await self.create_extracted_fact(
                conn,
                [],
                FactData(
                    cycle=cycle,
                    fact_type=FactType.ACTION,
                    description=(
                        f"Utilise {change.object_ref}. {change.reason or ''}"
                    ).strip(),
                    importance=2,
                    participants=[
                        FactParticipant(entity_ref=PROTAGONIST_REF, role="actor")
                    ],
                    semantic_key=use_key(change.object_ref),
                ),
            )

    # =========================================================================
    # FACTS AND EVENTS
    # =========================================================================

    async def create_extracted_fact(
        self, conn: Connection, errors: list, fact: FactData
    ) -> UUID | None:
        """A fact with its participants by id: every participant must resolve (an
        unresolved one raises RefUnresolved, so the fact is never written without it);
        an unresolved place is counted and the fact kept without it."""
        identity = await self.identity(conn)
        participants = [
            (await refs.required(identity, conn, p.entity_ref), p.role.value)
            for p in fact.participants
        ]
        location_id = await refs.optional(
            identity,
            conn,
            errors,
            "fact location",
            fact.location_ref,
            EntityType.LOCATION.value,
            live=True,
        )
        return await self.create_fact(conn, fact, participants, location_id)

    async def _schedule_event(self, conn: Connection, errors: list, event) -> UUID:
        """Schedule a future event from extraction; its place and participants that do
        not resolve are counted, the event is kept without them (C12)."""
        identity = await self.identity(conn)
        event_type = (
            event.event_type.value
            if hasattr(event.event_type, "value")
            else str(event.event_type)
        )
        event_id = await self.create_event(
            conn,
            event_type=event_type,
            title=event.title,
            planned_cycle=event.planned_cycle,
            description=event.description,
            time=event.time,
            location_id=await refs.optional(
                identity,
                conn,
                errors,
                "event location",
                event.location_ref,
                EntityType.LOCATION.value,
                live=True,
            ),
        )
        for entity_id in await refs.optional_ids(
            identity, conn, errors, "event participant", event.participants
        ):
            await self.add_event_participant(conn, event_id, entity_id)
        return event_id


async def _count_refusal(
    identity: IdentityService, conn: Connection, errors: list, entity_id: UUID
) -> None:
    """The refused part of an update whose allowed part is still applied: counted in
    `errors` and identity_events, like an UpdateRefused item (no story text)."""
    refusal = UpdateRefused(EntityType.PROTAGONIST.value, identity.game_id)
    errors.append({"code": refusal.code, "item": "update"})
    await identity.record_event(
        conn, refusal.code, None, entity_id, {"item": "update", **refusal.payload()}
    )


async def _turn_of(conn: Connection) -> UUID | None:
    """The turn the transaction is journaled under (the aliases a write learns carry it)."""
    return await current_turn_id(conn)
