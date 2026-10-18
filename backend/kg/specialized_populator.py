"""
LDVELH - Specialized Populators (Dedicated Tables Architecture)
WorldPopulator: Initial world generation processing
ExtractionPopulator: Narrative extraction processing
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from uuid import UUID

from schema import (
    ArcCreation,
    CharacterData,
    EntityCreation,
    EntityType,
    EntityUpdate,
    FactData,
    FactParticipant,
    FactType,
    InventoryChange,
    LocationData,
    NarrativeArcData,
    NarrativeExtraction,
    ObjectCreation,
    ObjectData,
    OrganizationData,
    PROTAGONIST_REF,
    RelationType,
    is_protagonist_ref,
)
from .item_writes import write_item, write_items
from .populator import KnowledgeGraphPopulator
from .semantic_keys import arrival_key, use_key

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)


# =============================================================================
# WORLD GENERATION POPULATOR
# =============================================================================


class WorldPopulator(KnowledgeGraphPopulator):
    """
    Populates the entire game world from a WorldGeneration output.
    Handles entity creation, FK resolution, relations, and arcs.
    """

    async def populate(
        self, world_gen, user_id: UUID | None = None,
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
        self, conn: Connection, world_gen, user_id: UUID | None,
        finalize: Callable[[Connection], Awaitable[None]] | None,
    ) -> UUID:
        """The whole world in one transaction on `conn`."""
        async with conn.transaction():
            # 1. Create game or rename existing
            if self.game_id:
                await self.rename_game(conn, world_gen.world.name)
            else:
                await self.create_game(
                    conn, world_gen.world.name, user_id
                )

            # 2. Store world metadata on games table
            await self.set_world_data(
                conn,
                world_gen.world,
                seed_words=world_gen.generation_seed_words,
            )

            # 3. Create station as top-level location
            await self._create_station_location(conn, world_gen.world)

            # 4. Create protagonist
            await self.create_protagonist(conn, world_gen.protagonist)

            # 5. Create companion
            await self.create_companion(
                conn, world_gen.companion
            )

            # 6. Create organizations (HQ refs resolved later)
            for org in world_gen.organizations:
                await self.create_organization(conn, org)

            # 7. Create locations (parent refs resolved later)
            for loc in world_gen.locations:
                await self.create_location(conn, loc)

            # 8. Resolve FK refs now that all entities exist
            await self._resolve_location_parents(conn, world_gen.locations)
            await self._resolve_org_headquarters(conn, world_gen.organizations)
            await self._resolve_protagonist_refs(conn, world_gen.protagonist)

            # 9. Create characters (with workplace/residence FKs)
            for char in world_gen.characters:
                wp_id = await self._resolve_location_id(
                    conn, char.workplace_ref
                )
                res_id = await self._resolve_location_id(
                    conn, char.residence_ref
                )
                await self.create_character(
                    conn, char, cycle=1,
                    workplace_id=wp_id, residence_id=res_id,
                )

            # 10. Create objects + inventory entries
            for obj in world_gen.inventory:
                obj_row_id = await self.create_object(conn, obj)
                if obj_row_id:
                    await self.add_to_inventory(
                        conn, obj_row_id,
                        quantity=obj.quantity, cycle=1, origin="initial",
                    )

            # 11. Load registry (entity_registry IDs for relations/arcs)
            await self.load_registry(conn)

            # 12. Create all explicit relations
            for rel in world_gen.initial_relations:
                result = await self.create_relation(conn, rel)
                if result is None:
                    logger.warning(
                        f"[POPULATE] Failed relation: "
                        f"{rel.source_ref} --{rel.relation_type.value}"
                        f"--> {rel.target_ref}"
                    )

            # 13. Create narrative arcs
            for arc in world_gen.narrative_arcs:
                await self.create_narrative_arc(conn, arc, cycle=1)

            # 14. Store arrival event
            await self._store_arrival_event(conn, world_gen.arrival_event)

            # 15. Set initial game state
            arrival_loc_id = await self._resolve_location_id(
                conn, world_gen.arrival_event.arrival_location_ref
            )
            await self.update_game_state(
                conn,
                cycle=1,
                date=world_gen.arrival_event.arrival_date,
                time=world_gen.arrival_event.time,
                location_id=arrival_loc_id,
            )

            # 16. Metadata
            await self._store_generation_meta(conn, world_gen)

            # 17. Caller's writes (engine, character, duration): all or nothing
            if finalize is not None:
                await finalize(conn)

            logger.info(
                f"World populated: {len(self.registry._by_name)} entities"
            )

        return self.game_id

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _create_station_location(self, conn: Connection, world) -> UUID:
        """Create the station as a top-level location."""
        loc_data = LocationData(
            name=world.name,
            location_type="station",
            description=world.description,
            atmosphere=world.atmosphere,
            notable_features=world.sectors if hasattr(world, "sectors") else [],
        )
        return await self.create_location(conn, loc_data, cycle=1)

    async def _resolve_location_parents(
        self, conn: Connection, locations: list
    ) -> None:
        """Update parent_id for locations with parent_location_ref."""
        for loc in locations:
            if loc.parent_location_ref:
                parent_id = await self._resolve_location_id(
                    conn, loc.parent_location_ref
                )
                if parent_id:
                    await conn.execute(
                        "UPDATE locations SET parent_id = $1"
                        " WHERE game_id = $2 AND LOWER(name) = LOWER($3)",
                        parent_id,
                        self.game_id,
                        loc.name,
                    )

    async def _resolve_org_headquarters(
        self, conn: Connection, organizations: list
    ) -> None:
        """Update headquarters_id for organizations."""
        for org in organizations:
            if org.headquarters_ref:
                hq_id = await self._resolve_location_id(
                    conn, org.headquarters_ref
                )
                if hq_id:
                    await conn.execute(
                        "UPDATE organizations SET headquarters_id = $1"
                        " WHERE game_id = $2 AND LOWER(name) = LOWER($3)",
                        hq_id,
                        self.game_id,
                        org.name,
                    )

    async def _resolve_protagonist_refs(
        self, conn: Connection, protagonist
    ) -> None:
        """Update protagonist employer_id and residence_id."""
        if protagonist.employer_ref:
            emp_id = await self._resolve_organization_id(
                conn, protagonist.employer_ref
            )
            if emp_id:
                await conn.execute(
                    "UPDATE protagonists SET employer_id = $1"
                    " WHERE game_id = $2",
                    emp_id,
                    self.game_id,
                )
        if protagonist.residence_ref:
            res_id = await self._resolve_location_id(
                conn, protagonist.residence_ref
            )
            if res_id:
                await conn.execute(
                    "UPDATE protagonists SET residence_id = $1"
                    " WHERE game_id = $2",
                    res_id,
                    self.game_id,
                )

    async def _store_arrival_event(
        self, conn: Connection, arrival
    ) -> None:
        """Store arrival as facts + event + chronology entry."""

        # 1. Main arrival fact
        await self.create_fact(
            conn,
            FactData(
                cycle=1,
                fact_type=FactType.ENCOUNTER,
                description=(
                    f"Arrivée sur la station via {arrival.arrival_method}"
                ),
                location_ref=arrival.arrival_location_ref,
                time=getattr(arrival, "time", None),
                importance=4,
                participants=[
                    FactParticipant(entity_ref=PROTAGONIST_REF, role="actor")
                ],
                semantic_key=arrival_key("station"),
            ),
        )

        # 2. Milestone event
        event_id = await self.create_event(
            conn,
            event_type="milestone",
            title="Arrivée sur la station",
            planned_cycle=1,
            description=f"Arrivée via {arrival.arrival_method}",
            time=getattr(arrival, "time", None),
            location_ref=arrival.arrival_location_ref,
            completed=True,
        )

        # 3. Add protagonist as participant
        protagonist_ids = self.registry.get_by_type(EntityType.PROTAGONIST)
        if protagonist_ids:
            await self.add_event_participant(conn, event_id, protagonist_ids[0])

        # 4. Additional facts
        sensory = getattr(arrival, "immediate_sensory_details", None)
        if sensory:
            sensory_text = (
                ". ".join(sensory) if isinstance(sensory, list) else sensory
            )
            await self.create_fact(
                conn,
                FactData(
                    cycle=1,
                    fact_type=FactType.ATMOSPHERE,
                    description=f"Premières impressions : {sensory_text[:250]}",
                    location_ref=arrival.arrival_location_ref,
                    importance=2,
                    participants=[],
                    semantic_key=arrival_key("sensory"),
                ),
            )

        incident = getattr(arrival, "optional_incident", None)
        if incident:
            await self.create_fact(
                conn,
                FactData(
                    cycle=1,
                    fact_type=FactType.ACTION,
                    description=incident[:300],
                    location_ref=arrival.arrival_location_ref,
                    importance=3,
                    participants=[
                        FactParticipant(entity_ref=PROTAGONIST_REF, role="actor")
                    ],
                    semantic_key=arrival_key("incident"),
                ),
            )

        mood = getattr(arrival, "initial_mood", None)
        if mood:
            await self.create_fact(
                conn,
                FactData(
                    cycle=1,
                    fact_type=FactType.STATE_CHANGE,
                    description=f"État à l'arrivée : {mood}",
                    importance=2,
                    participants=[
                        FactParticipant(entity_ref=PROTAGONIST_REF, role="actor")
                    ],
                    semantic_key=arrival_key("mood"),
                ),
            )

        need = getattr(arrival, "immediate_need", None)
        if need:
            await self.create_fact(
                conn,
                FactData(
                    cycle=1,
                    fact_type=FactType.OBSERVATION,
                    description=f"Besoin immédiat : {need}",
                    importance=2,
                    participants=[
                        FactParticipant(entity_ref=PROTAGONIST_REF, role="actor")
                    ],
                    semantic_key=arrival_key("need"),
                ),
            )

        # 5. Chronology entry (replaces old cycle_summary)
        await self.save_chronology_entry(
            conn,
            cycle=0,
            summary=arrival.build_arrival_summary(),
            time=getattr(arrival, "time", None),
            location_ref=arrival.arrival_location_ref,
        )

    async def _store_generation_meta(self, conn: Connection, world_gen) -> None:
        """Store generation metadata."""
        await self.update_game_timestamp(conn)
        await self.log_extraction(
            conn,
            cycle=0,
            stats={
                "entities_created": len(self.registry._by_name),
                "relations_created": (
                    len(world_gen.initial_relations)
                    if hasattr(world_gen, "initial_relations")
                    else 0
                ),
            },
        )


# =============================================================================
# NARRATIVE EXTRACTION POPULATOR
# =============================================================================


class ExtractionPopulator(KnowledgeGraphPopulator):
    """
    Processes narrative extractions into the database.
    Routes entity creation/updates to the correct dedicated tables.
    """

    async def process_extraction(
        self, extraction: NarrativeExtraction
    ) -> dict:
        """Process a complete narrative extraction."""
        stats = {
            "facts_created": 0,
            "entities_created": 0,
            "objects_created": 0,
            "entities_updated": 0,
            "relations_created": 0,
            "relations_ended": 0,
            "credits_changed": 0,
            "arcs_created": 0,
            "errors": [],
        }

        cycle = extraction.cycle
        prefix = "[EXTRACTION] "

        async with self.pool.acquire() as conn:
            async def items(label, values, write, counter=None):
                await write_items(conn, stats, label, values, write, counter, prefix)

            async with conn.transaction():
                if not self.registry._by_name:
                    await self.load_registry(conn)

                # One SAVEPOINT per item: a failed item never aborts the others.
                await items("Entity creation", extraction.entities_created,
                            lambda e: self._process_entity_creation(conn, e, cycle),
                            "entities_created")
                await items("Object creation", extraction.objects_created,
                            lambda o: self._created(self._process_object_creation(conn, o, cycle)),
                            "objects_created")

                # Reload registry (new entities registered by triggers)
                await self.load_registry(conn)

                await items("Entity update", extraction.entities_updated,
                            lambda u: self._created(self._process_entity_update(conn, u, cycle)),
                            "entities_updated")
                await items("Entity removal", extraction.entities_removed,
                            lambda r: self._remove_detected(conn, r.entity_ref, r.cycle))
                await items("Fact", extraction.facts,
                            lambda f: self.create_fact(conn, f), "facts_created")
                # Skip OWNS: handled by inventory
                await items("Relation creation", [
                    rc for rc in extraction.relations_created
                    if rc.relation.relation_type != RelationType.OWNS
                ], lambda rc: self.create_relation(conn, rc.relation, rc.cycle),
                    "relations_created")
                await items("Relation end", extraction.relations_ended,
                            lambda re: self._created(self.end_relation(
                                conn, re.source_ref, re.target_ref, re.relation_type,
                                re.cycle, re.reason)),
                            "relations_ended")
                await items("Credits", extraction.credit_transactions,
                            lambda tx: self._credit(conn, stats, tx, cycle), "credits_changed")
                await items("Inventory change", extraction.inventory_changes,
                            lambda inv: self._process_inventory_change(conn, inv, cycle))
                await items("Arc creation", extraction.arcs_created,
                            lambda arc: self._created(
                                self._create_arc_from_extraction(conn, arc, cycle)),
                            "arcs_created")
                # Update arc progress (simplified — Director manages arcs now)
                await items("Arc update", extraction.arcs_updated,
                            lambda au: self.update_arc(conn, arc_title=au.arc_title,
                                                       intensity=au.intensity),
                            "arcs_updated")
                await items("Arc resolution", extraction.arcs_resolved,
                            lambda res: self.resolve_arc(conn, res.arc_title,
                                                         res.resolution, cycle))
                await items("Event", extraction.events_scheduled,
                            lambda ev: self._schedule_event(conn, ev))
                await items("Ambient update", extraction.ambient_updates,
                            lambda amb: self.update_entity(conn, amb.entity_type,
                                                           amb.entity_ref,
                                                           {"ambient": amb.ambient}),
                            "ambients_updated")

                if extraction.segment_summary:
                    await write_item(conn, stats["errors"], "Chronology",
                                     lambda: self.save_chronology_entry(
                                         conn,
                                         cycle=cycle,
                                         summary=extraction.segment_summary,
                                         time=extraction.time,
                                         location_ref=extraction.current_location_ref,
                                         npc_refs=extraction.key_npcs_present or None,
                                     ), prefix)

                await self.log_extraction(conn, cycle, stats)

        return stats

    @staticmethod
    async def _created(write: Awaitable[object]) -> bool:
        """Await a write that returns nothing: reaching the end means it was applied."""
        await write
        return True

    async def _remove_detected(self, conn: Connection, entity_ref: str, cycle: int) -> bool:
        et = await self._detect_entity_type(conn, entity_ref)
        return bool(et) and await self.remove_entity(conn, entity_ref, et, cycle)

    async def _credit(self, conn: Connection, stats: dict, tx, cycle: int) -> bool:
        success, _, error = await self.credit_transaction(conn, tx.amount, cycle, tx.description)
        if not success and error:
            stats["errors"].append(f"Credits: {error}")
        return success

    # =========================================================================
    # ENTITY CREATION ROUTING
    # =========================================================================

    async def _process_entity_creation(
        self, conn: Connection, creation: EntityCreation, cycle: int
    ) -> bool:
        """Route entity creation to the correct dedicated table. True when written."""
        et = creation.entity_type
        data = creation.data or {}
        if is_protagonist_ref(creation.name):
            logger.warning(f"[EXTRACT] Skipping {et} named after the reserved reference"
                           f" '{creation.name}' (#28)")
            return False

        if et == EntityType.CHARACTER:
            char_data = CharacterData(
                name=creation.name,
                known_by_protagonist=creation.known_by_protagonist,
                unknown_name=creation.unknown_name,
                **{k: v for k, v in data.items()
                   if k not in ("workplace_ref", "residence_ref")},
            )
            wp_id = await self._resolve_location_id(
                conn, data.get("workplace_ref")
            )
            res_id = await self._resolve_location_id(
                conn, data.get("residence_ref")
            )
            await self.create_character(
                conn, char_data, cycle, wp_id, res_id
            )

        elif et == EntityType.LOCATION:
            loc_data = LocationData(
                name=creation.name,
                **{k: v for k, v in data.items()
                   if k != "parent_location_ref"},
            )
            parent_id = await self._resolve_location_id(
                conn, data.get("parent_location_ref")
            )
            await self.create_location(conn, loc_data, cycle, parent_id)

        elif et == EntityType.ORGANIZATION:
            org_data = OrganizationData(
                name=creation.name,
                **{k: v for k, v in data.items()
                   if k != "headquarters_ref"},
            )
            hq_id = await self._resolve_location_id(
                conn, data.get("headquarters_ref")
            )
            await self.create_organization(conn, org_data, cycle, hq_id)

        elif et == EntityType.OBJECT:
            obj_data = ObjectData(name=creation.name, **data)
            obj_id = await self.create_object(conn, obj_data, cycle)
            if obj_id:
                await self.add_to_inventory(
                    conn, obj_id, cycle=cycle, origin="discovered"
                )

        else:
            logger.warning(
                f"[EXTRACT] Unsupported entity type: {et} for '{creation.name}'"
            )
            return False
        return True

    async def _process_object_creation(
        self, conn: Connection, obj_creation: ObjectCreation, cycle: int
    ) -> None:
        """Create an object from acquisition and add to protagonist inventory."""
        obj_data = ObjectData(
            name=obj_creation.name,
            category=obj_creation.category,
            description=obj_creation.description,
            transportable=obj_creation.transportable,
            stackable=obj_creation.stackable,
            base_value=obj_creation.base_value,
        )
        obj_id = await self.create_object(conn, obj_data, cycle)
        if obj_id:
            # Store canonical_name if provided
            canonical = getattr(obj_creation, "canonical_name", None)
            if canonical:
                await conn.execute(
                    "UPDATE objects SET canonical_name = $1 WHERE id = $2",
                    canonical, obj_id,
                )
            await self.add_to_inventory(
                conn,
                obj_id,
                quantity=obj_creation.quantity,
                cycle=cycle,
                origin="acquired",
            )

    async def create_object_with_canonical(
        self, conn: Connection, obj_creation: ObjectCreation, cycle: int
    ) -> UUID | None:
        """Create object with canonical_name dedup.

        If an active object with the same canonical_name already exists,
        just add to inventory instead of creating a new record.
        """
        canonical = getattr(obj_creation, "canonical_name", None)
        if canonical:
            existing = await conn.fetchval(
                "SELECT id FROM objects"
                " WHERE game_id = $1 AND canonical_name = $2"
                " AND removed_cycle IS NULL",
                self.game_id, canonical,
            )
            if existing:
                logger.info(
                    f"[CANONICAL] Object '{canonical}' already exists, "
                    f"adding to inventory"
                )
                await self.add_to_inventory(
                    conn, existing,
                    quantity=obj_creation.quantity,
                    cycle=cycle, origin="acquired",
                )
                return existing

        # No canonical match — create normally
        await self._process_object_creation(conn, obj_creation, cycle)
        # Resolve the newly created object ID
        row = await conn.fetchval(
            "SELECT id FROM objects"
            " WHERE game_id = $1 AND LOWER(name) = LOWER($2)"
            " AND removed_cycle IS NULL"
            " ORDER BY created_at DESC LIMIT 1",
            self.game_id, obj_creation.name,
        )
        return row

    # =========================================================================
    # ENTITY UPDATE ROUTING
    # =========================================================================

    async def _process_entity_update(
        self, conn: Connection, update: EntityUpdate, cycle: int
    ) -> None:
        """Route entity update to the correct dedicated table."""
        entity_type = update.entity_type
        if not entity_type:
            entity_type = await self._detect_entity_type(
                conn, update.entity_ref
            )
        if not entity_type:
            logger.warning(
                f"[UPDATE] Unknown entity type for '{update.entity_ref}'"
            )
            return

        # Reveal identity
        if update.now_known and entity_type == EntityType.CHARACTER:
            await self.mark_character_known(
                conn, update.entity_ref, update.real_name
            )

        # Field changes
        if update.changes:
            await self.update_entity(
                conn, entity_type, update.entity_ref, update.changes
            )

        # Skill changes
        if update.skills_changed:
            await self._update_entity_skills(
                conn, entity_type, update.entity_ref, update.skills_changed,
                cycle,
            )

        # Mark as removed
        if update.removed:
            await self.remove_entity(
                conn, update.entity_ref, entity_type, cycle
            )

    async def _detect_entity_type(
        self, conn: Connection, name: str
    ) -> EntityType | None:
        """Detect entity type from entity_registry."""
        row = await conn.fetchrow(  # find_entity maps PROTAGONIST_REF too (#28)
            "SELECT entity_type FROM entity_registry WHERE id = find_entity($1, $2)",
            self.game_id,
            name,
        )
        if row:
            try:
                return EntityType(row["entity_type"])
            except ValueError:
                pass
        return None

    async def _update_entity_skills(
        self,
        conn: Connection,
        entity_type: EntityType,
        entity_ref: str,
        skills: list,
        cycle: int,
    ) -> None:
        """Update skills for a character or protagonist."""
        if entity_type == EntityType.CHARACTER:
            char_id = await conn.fetchval(
                "SELECT id FROM characters"
                " WHERE game_id = $1 AND LOWER(name) = LOWER($2)",
                self.game_id,
                entity_ref,
            )
            if char_id:
                for skill in skills:
                    await self.update_skill(
                        conn, skill, cycle, character_id=char_id
                    )
        elif entity_type == EntityType.PROTAGONIST:
            proto_id = await self._resolve_protagonist_id(conn)
            if proto_id:
                for skill in skills:
                    await self.update_skill(
                        conn, skill, cycle, protagonist_id=proto_id
                    )

    # =========================================================================
    # INVENTORY CHANGES
    # =========================================================================

    async def _process_inventory_change(
        self, conn: Connection, change: InventoryChange, cycle: int
    ) -> None:
        """Process acquire/lose/use inventory actions."""
        if change.action == "acquire":
            if change.object_hint:
                return  # Handled by objects_created
            if change.object_ref:
                obj_id = await self._resolve_object_id(
                    conn, change.object_ref
                )
                if obj_id:
                    await self.add_to_inventory(
                        conn, obj_id,
                        quantity=change.quantity_delta,
                        cycle=cycle, origin="acquired",
                    )

        elif change.action == "lose" and change.object_ref:
            obj_id = await self._resolve_object_id(conn, change.object_ref)
            if obj_id:
                await self.remove_from_inventory(
                    conn, obj_id, change.quantity_delta
                )

        elif change.action == "use" and change.object_ref:
            await self.create_fact(
                conn,
                FactData(
                    cycle=cycle,
                    fact_type=FactType.ACTION,
                    description=(
                        f"Utilise {change.object_ref}."
                        f" {change.reason or ''}"
                    ).strip(),
                    importance=2,
                    participants=[
                        FactParticipant(entity_ref=PROTAGONIST_REF, role="actor")
                    ],
                    semantic_key=use_key(change.object_ref),
                ),
            )

    # =========================================================================
    # NARRATIVE ARC FROM EXTRACTION
    # =========================================================================

    async def _create_arc_from_extraction(
        self, conn: Connection, arc: ArcCreation, cycle: int
    ) -> UUID:
        """Create a narrative arc from extraction output.

        intensity is passed on only when the extractor sent it, so a re-listed arc keeps
        its stored intensity (#87).
        """
        explicit = {"intensity": arc.intensity} if "intensity" in arc.model_fields_set else {}
        arc_data = NarrativeArcData(
            title=arc.title,
            domain=arc.domain,
            description=arc.description,
            involved_entities=arc.involved_entities,
            **explicit,
        )
        return await self.create_narrative_arc(conn, arc_data, cycle)

    # =========================================================================
    # EVENT SCHEDULING
    # =========================================================================

    async def _schedule_event(self, conn: Connection, event) -> UUID:
        """Schedule a future event from extraction."""
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
            location_ref=event.location_ref,
        )

        for participant_ref in event.participants:
            entity_id = self.registry.resolve(participant_ref)
            if entity_id:
                await self.add_event_participant(conn, event_id, entity_id)

        return event_id
