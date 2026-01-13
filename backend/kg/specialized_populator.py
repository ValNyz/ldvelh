"""
LDVELH - Specialized Populators (EAV Architecture)
WorldPopulator: Initial world generation processing
ExtractionPopulator: Narrative extraction processing

Utilise KnowledgeGraphPopulator et KnowledgeGraphReader
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from schema import (
    ArrivalEventData,
    AttributeKey,
    AttributeWithVisibility,
    CommitmentType,
    EntityCreation,
    EntityUpdate,
    InventoryChange,
    NarrativeExtraction,
    NarrativeArcData,
    ObjectCreation,
    RelationData,
    RelationType,
    EntityType,
    FactData,
    FactParticipant,
    FactType,
)
from .populator import KnowledgeGraphPopulator
from .reader import KnowledgeGraphReader

if TYPE_CHECKING:
    from asyncpg import Connection

logger = logging.getLogger(__name__)


# =============================================================================
# WORLD GENERATION POPULATOR
# =============================================================================


class WorldPopulator(KnowledgeGraphPopulator):
    """
    Specialized populator for initial world generation.
    Takes a complete WorldGeneration and populates the entire KG.
    """

    async def populate(self, world_gen) -> UUID:
        """Main entry point - creates game and populates everything"""

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 1. Create game OR rename existing
                if self.game_id:
                    await self.rename_game(conn, world_gen.world.name)
                else:
                    await self.create_game(conn, world_gen.world.name)

                # 2. Create world as top-level location
                await self._create_world(conn, world_gen.world)

                # 3. Create protagonist
                await self.create_protagonist(conn, world_gen.protagonist)

                # 4. Create AI
                await self.create_ai(conn, world_gen.personal_ai)

                # 5. Create organizations
                for org in world_gen.organizations:
                    await self.create_organization(conn, org)

                # 6. Create locations (two passes for parent refs)
                await self._create_locations_two_pass(conn, world_gen.locations)

                # 7. Update organization HQ refs
                await self._update_org_headquarters(conn, world_gen.organizations)

                # 8. Create characters
                for char in world_gen.characters:
                    await self.create_character(conn, char)

                # 9. Create inventory
                for obj in world_gen.inventory:
                    await self.create_object(
                        conn, obj, owner_ref=world_gen.protagonist.name
                    )

                # 10. Create all explicit relations
                for rel in world_gen.initial_relations:
                    result = await self.create_relation(conn, rel)
                    if result is None:
                        logger.warning(
                            f"[POPULATE] Failed to create relation: "
                            f"{rel.source_ref} --{rel.relation_type.value}--> {rel.target_ref}"
                        )

                # 11. Create narrative arcs as commitments
                for arc in world_gen.narrative_arcs:
                    await self._create_narrative_arc(conn, arc)

                # 12. Store arrival event metadata
                await self._store_arrival_event(conn, world_gen.arrival_event)

                # 13. Store generation metadata
                await self._store_generation_meta(conn, world_gen)

                logger.info(f"World populated: {len(self.registry._by_name)} entities")

        return self.game_id

    async def _create_world(self, conn: Connection, world) -> UUID:
        """Create the station as top-level location entity"""
        entity_id = await self.upsert_entity(conn, EntityType.LOCATION, world.name)

        # Set all world attributes
        attrs = [
            AttributeWithVisibility(
                key=AttributeKey.LOCATION_TYPE,
                value=world.station_type
                if hasattr(world, "station_type")
                else "station",
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.ATMOSPHERE,
                value=world.atmosphere if hasattr(world, "atmosphere") else "",
                known_by_protagonist=True,
            ),
            AttributeWithVisibility(
                key=AttributeKey.DESCRIPTION,
                value=world.description if hasattr(world, "description") else "",
                known_by_protagonist=True,
            ),
        ]

        # Add sectors as notable_features
        if hasattr(world, "sectors") and world.sectors:
            attrs.append(
                AttributeWithVisibility(
                    key=AttributeKey.NOTABLE_FEATURES,
                    value=json.dumps(world.sectors),
                    known_by_protagonist=True,
                )
            )

        await self.set_attributes(
            conn, entity_id, attrs, cycle=1, entity_type=EntityType.LOCATION
        )

        return entity_id

    async def _create_locations_two_pass(
        self, conn: Connection, locations: list
    ) -> None:
        """Create locations in two passes to handle parent refs"""
        for loc in locations:
            await self.upsert_entity(conn, EntityType.LOCATION, loc.name)

        for loc in locations:
            await self.create_location(conn, loc)

    async def _update_org_headquarters(
        self, conn: Connection, organizations: list
    ) -> None:
        """Update organization HQ refs"""
        for org in organizations:
            if hasattr(org, "headquarters_ref") and org.headquarters_ref:
                hq_id = self.registry.resolve(org.headquarters_ref)
                org_id = self.registry.resolve(org.name)
                if hq_id and org_id:
                    await self.update_entity_fk(
                        conn,
                        EntityType.ORGANIZATION,
                        org_id,
                        "headquarters_id",
                        hq_id,
                    )

    async def _create_narrative_arc(
        self, conn: Connection, arc: NarrativeArcData
    ) -> UUID:
        """Create a narrative arc as a commitment"""
        arc_type = (
            arc.arc_type.value if hasattr(arc.arc_type, "value") else arc.arc_type
        )

        commitment_id = await self.create_commitment(
            conn,
            commitment_type=arc_type,
            description=f"{arc.title}: {arc.description}",
            cycle=1,
            deadline_cycle=arc.deadline_cycle
            if hasattr(arc, "deadline_cycle")
            else None,
        )

        if hasattr(arc, "arc_type") and arc.arc_type == CommitmentType.ARC:
            await self.create_commitment_arc(
                conn,
                commitment_id,
                objective=arc.title,
                obstacle=arc.stakes if hasattr(arc, "stakes") else "",
            )

        for entity_name in (
            arc.involved_entities if hasattr(arc, "involved_entities") else []
        ):
            entity_id = self.registry.resolve(entity_name)
            if entity_id:
                await self.add_commitment_entity(
                    conn, commitment_id, entity_id, role="involved"
                )
                logger.info(f"[ARC] Linked '{entity_name}' to '{arc.title}'")
            else:
                logger.warning(
                    f"[ARC] Entity not found for arc '{arc.title}': '{entity_name}'"
                )
                logger.info(
                    f"[ARC] Available entities: {list(self.registry._by_name.keys())[:15]}..."
                )

        return commitment_id

    async def _store_arrival_event(
        self, conn: Connection, arrival: ArrivalEventData
    ) -> None:
        """Store arrival as milestone event with source fact + cycle summary"""

        # 1. Créer le fact principal d'arrivée
        arrival_fact_id = await self.create_fact(
            conn,
            FactData(
                cycle=1,
                fact_type=FactType.ENCOUNTER,
                description=f"Arrivée sur la station via {arrival.arrival_method}",
                location_ref=arrival.arrival_location_ref,
                time=arrival.time if hasattr(arrival, "time") else None,
                importance=4,
                participants=[FactParticipant(entity_ref="Valentin", role="actor")],
                semantic_key="valentin:arrival:station",
            ),
        )

        # 2. Créer l'événement milestone lié au fact
        event_id = await self.create_event(
            conn,
            event_type="milestone",
            title="Arrivée sur la station",
            planned_cycle=1,
            description=f"Arrivée via {arrival.arrival_method}",
            time=arrival.time if hasattr(arrival, "time") else None,
            location_ref=arrival.arrival_location_ref,
            completed=True,
            source_fact_id=arrival_fact_id,
        )

        # 3. Ajouter le protagoniste comme participant
        protagonist_ids = self.registry.get_by_type(EntityType.PROTAGONIST)
        if protagonist_ids:
            await self.add_event_participant(
                conn, event_id, protagonist_ids[0], role="protagonist"
            )

        # 4. Créer facts supplémentaires (indépendants, même cycle)

        # Atmosphère/sensations
        sensory = getattr(arrival, "immediate_sensory_details", None)
        if sensory:
            sensory_text = ". ".join(sensory) if isinstance(sensory, list) else sensory
            await self.create_fact(
                conn,
                FactData(
                    cycle=1,
                    fact_type=FactType.ATMOSPHERE,
                    description=f"Premières impressions : {sensory_text[:250]}",
                    location_ref=arrival.arrival_location_ref,
                    importance=2,
                    participants=[],
                    semantic_key="valentin:arrival:sensory",
                ),
            )

        # Incident
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
                    participants=[FactParticipant(entity_ref="Valentin", role="actor")],
                    semantic_key="valentin:arrival:incident",
                ),
            )

        # État émotionnel
        mood = getattr(arrival, "initial_mood", None)
        if mood:
            await self.create_fact(
                conn,
                FactData(
                    cycle=1,
                    fact_type=FactType.STATE_CHANGE,
                    description=f"État à l'arrivée : {mood}",
                    importance=2,
                    participants=[FactParticipant(entity_ref="Valentin", role="actor")],
                    semantic_key="valentin:arrival:mood",
                ),
            )

        # Besoin immédiat
        need = getattr(arrival, "immediate_need", None)
        if need:
            await self.create_fact(
                conn,
                FactData(
                    cycle=1,
                    fact_type=FactType.OBSERVATION,
                    description=f"Besoin immédiat : {need}",
                    importance=2,
                    participants=[FactParticipant(entity_ref="Valentin", role="actor")],
                    semantic_key="valentin:arrival:need",
                ),
            )

        # 5. Créer le cycle_summary
        summary_id = await self.save_cycle_summary(
            conn,
            cycle=0,
            date=arrival.arrival_date,
            summary=arrival._build_arrival_summary(),
        )

        # 6. Lier l'event au cycle_summary
        await self.add_event_to_cycle_summary(
            conn,
            cycle_summary_id=summary_id,
            event_id=event_id,
            role="primary",
            display_order=0,
        )

    async def _store_generation_meta(self, conn: Connection, world_gen) -> None:
        """Store generation metadata"""
        await self.update_game_timestamp(conn)

        await self.log_extraction(
            conn,
            cycle=0,
            stats={
                "entities_created": len(self.registry._by_name),
                "relations_created": len(world_gen.initial_relations)
                if hasattr(world_gen, "initial_relations")
                else 0,
            },
        )


# =============================================================================
# NARRATIVE EXTRACTION POPULATOR
# =============================================================================


class ExtractionPopulator(KnowledgeGraphPopulator):
    """
    Specialized populator for processing narrative extractions.
    Uses unified EAV format for all entity types.
    """

    def _get_reader(self) -> KnowledgeGraphReader:
        """Crée un reader pour les lookups"""
        return KnowledgeGraphReader(self.pool, self.game_id)

    async def process_extraction(self, extraction: NarrativeExtraction) -> dict:
        """Process a complete narrative extraction."""
        stats = {
            "facts_created": 0,
            "entities_created": 0,
            "objects_created": 0,
            "entities_updated": 0,
            "relations_created": 0,
            "relations_ended": 0,
            "gauges_changed": 0,
            "credits_changed": 0,
            "commitments_created": 0,
            "errors": [],
        }

        cycle = extraction.cycle

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if not self.registry._by_name:
                    await self.load_registry(conn)

                # 1. Create new entities (unified EAV format)
                for entity in extraction.entities_created:
                    try:
                        await self._process_entity_creation(conn, entity, cycle)
                        stats["entities_created"] += 1
                    except Exception as e:
                        logger.error(f"Entity creation error: {e}")
                        stats["errors"].append(f"Entity creation: {e}")

                # 2. Create objects from acquisition
                for obj_creation in extraction.objects_created:
                    try:
                        await self._process_object_creation(conn, obj_creation, cycle)
                        stats["objects_created"] += 1
                    except Exception as e:
                        logger.error(f"Object creation error: {e}")
                        stats["errors"].append(f"Object creation: {e}")

                # 3. Process entity updates
                for update in extraction.entities_updated:
                    try:
                        await self._process_entity_update(conn, update, cycle)
                        stats["entities_updated"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Entity update: {e}")

                # 4. Process entity removals
                for removal in extraction.entities_removed:
                    await self.remove_entity(
                        conn, removal.entity_ref, removal.cycle, removal.reason
                    )

                # 5. Create facts
                for fact in extraction.facts:
                    result = await self.create_fact(conn, fact)
                    if result:
                        stats["facts_created"] += 1

                # 6. Create new relations (NO owns)
                for rel_creation in extraction.relations_created:
                    if rel_creation.relation.relation_type == RelationType.OWNS:
                        continue
                    result = await self.create_relation(
                        conn, rel_creation.relation, rel_creation.cycle
                    )
                    if result:
                        stats["relations_created"] += 1

                # 7. End relations
                for rel_end in extraction.relations_ended:
                    await self.end_relation(
                        conn,
                        rel_end.source_ref,
                        rel_end.target_ref,
                        rel_end.relation_type,
                        rel_end.cycle,
                        rel_end.reason,
                    )
                    stats["relations_ended"] += 1

                # 8. Process gauge changes
                for gauge in extraction.gauge_changes:
                    success, _, _ = await self.update_gauge(
                        conn, gauge.gauge, gauge.delta, cycle
                    )
                    if success:
                        stats["gauges_changed"] += 1

                # 9. Process credit transactions
                for tx in extraction.credit_transactions:
                    success, _, error = await self.credit_transaction(
                        conn, tx.amount, cycle, tx.description
                    )
                    if success:
                        stats["credits_changed"] += 1
                    elif error:
                        stats["errors"].append(f"Credits: {error}")

                # 10. Process inventory changes
                for inv in extraction.inventory_changes:
                    await self._process_inventory_change(conn, inv, cycle)

                # 11. Create commitments
                for commit in extraction.commitments_created:
                    await self._create_extraction_commitment(conn, commit, cycle)
                    stats["commitments_created"] += 1

                # 12. Resolve commitments
                for resolution in extraction.commitments_resolved:
                    await self._resolve_extraction_commitment(conn, resolution, cycle)

                # 13. Schedule events
                for event in extraction.events_scheduled:
                    await self._schedule_extraction_event(conn, event, cycle)

                # 14. Store extraction log
                await self.log_extraction(conn, cycle, stats)

                # # 15. Store cycle summary
                # await self.save_cycle_summary(
                #     conn, cycle, summary=extraction.segment_summary, date=data["date"]
                # )

        return stats

    async def _process_entity_creation(
        self, conn: Connection, creation: EntityCreation, cycle: int
    ) -> UUID:
        """Process a new entity creation using unified EAV format."""
        # Create base entity
        entity_id = await self.upsert_entity(
            conn,
            creation.entity_type,
            creation.name,
            creation.aliases,
            cycle,
            creation.known_by_protagonist,
            creation.unknown_name,
        )

        # Set all attributes from unified format
        if creation.attributes:
            await self.set_attributes(
                conn,
                entity_id,
                creation.attributes,
                cycle,
                entity_type=creation.entity_type,
            )

        # Handle FK references via update_entity_fk
        if creation.entity_type == EntityType.LOCATION and creation.parent_location_ref:
            parent_id = self.registry.resolve(creation.parent_location_ref)
            if parent_id:
                await self.update_entity_fk(
                    conn,
                    EntityType.LOCATION,
                    entity_id,
                    "parent_location_id",
                    parent_id,
                )

        if (
            creation.entity_type == EntityType.ORGANIZATION
            and creation.headquarters_ref
        ):
            hq_id = self.registry.resolve(creation.headquarters_ref)
            if hq_id:
                await self.update_entity_fk(
                    conn, EntityType.ORGANIZATION, entity_id, "headquarters_id", hq_id
                )

        if creation.entity_type == EntityType.AI and creation.creator_ref:
            creator_id = self.registry.resolve(creation.creator_ref)
            if creator_id:
                await self.update_entity_fk(
                    conn, EntityType.AI, entity_id, "creator_id", creator_id
                )

        # Auto-create spatial relations for characters
        if creation.entity_type == EntityType.CHARACTER:
            if creation.workplace_ref:
                await self.create_relation(
                    conn,
                    RelationData(
                        source_ref=creation.name,
                        target_ref=creation.workplace_ref,
                        relation_type=RelationType.WORKS_AT,
                    ),
                    cycle,
                )
            if creation.residence_ref:
                await self.create_relation(
                    conn,
                    RelationData(
                        source_ref=creation.name,
                        target_ref=creation.residence_ref,
                        relation_type=RelationType.LIVES_AT,
                    ),
                    cycle,
                )

        return entity_id

    async def _process_object_creation(
        self, conn: Connection, obj_creation: ObjectCreation, cycle: int
    ) -> UUID:
        """Process an object creation from inventory acquisition."""
        # Get protagonist
        protagonist_ids = self.registry.get_by_type(EntityType.PROTAGONIST)
        if not protagonist_ids:
            raise ValueError("Protagonist not found")
        protagonist_id = protagonist_ids[0]
        protagonist_name = self.registry.get_name(protagonist_id)

        # Create entity
        entity_id = await self.upsert_entity(
            conn, EntityType.OBJECT, obj_creation.name, cycle=cycle
        )

        # Set attributes
        if obj_creation.attributes:
            await self.set_attributes(
                conn,
                entity_id,
                obj_creation.attributes,
                cycle,
                entity_type=EntityType.OBJECT,
            )

        # Create owns relation
        await self.create_relation(
            conn,
            RelationData(
                source_ref=protagonist_name,
                target_ref=obj_creation.name,
                relation_type=RelationType.OWNS,
                quantity=obj_creation.quantity,
                origin="acquired",
            ),
            cycle,
        )

        return entity_id

    async def _process_entity_update(
        self, conn: Connection, update: EntityUpdate, cycle: int
    ) -> None:
        """Process an entity update using EAV attributes"""
        entity_id = self.registry.resolve(update.entity_ref)
        if not entity_id:
            raise KeyError(f"Entity not found: {update.entity_ref}")

        # Update aliases
        if update.new_aliases:
            await self.update_entity_aliases(conn, entity_id, update.new_aliases)

        # Update known status
        if update.now_known:
            await self.mark_entity_known(conn, entity_id, update.real_name)

        # Update attributes
        if update.attributes_changed:
            reader = self._get_reader()
            entity = await reader.get_entity_by_id(conn, entity_id)
            entity_type = EntityType(entity["type"]) if entity else None

            await self.set_attributes(
                conn,
                entity_id,
                update.attributes_changed,
                cycle,
                entity_type=entity_type,
            )

        # Update skills
        for skill in update.skills_changed:
            await self.set_skill(conn, entity_id, skill, cycle)

    async def _process_inventory_change(
        self, conn: Connection, change: InventoryChange, cycle: int
    ) -> None:
        """Process inventory changes (acquire with ref, lose, use)"""
        protagonist_ids = self.registry.get_by_type(EntityType.PROTAGONIST)
        if not protagonist_ids:
            return
        protagonist_name = self.registry.get_name(protagonist_ids[0])

        if change.action == "acquire":
            if change.object_hint:
                return  # Handled by objects_created

            if change.object_ref:
                await self.create_relation(
                    conn,
                    RelationData(
                        source_ref=protagonist_name,
                        target_ref=change.object_ref,
                        relation_type=RelationType.OWNS,
                    ),
                    cycle,
                )

        elif change.action == "lose" and change.object_ref:
            await self.end_relation(
                conn,
                protagonist_name,
                change.object_ref,
                RelationType.OWNS,
                cycle,
                change.reason,
            )

        elif change.action == "use" and change.object_ref:
            from schema import FactData, FactParticipant

            await self.create_fact(
                conn,
                FactData(
                    cycle=cycle,
                    fact_type=FactType.ACTION,
                    description=f"Utilise {change.object_ref}. {change.reason or ''}",
                    importance=2,
                    participants=[FactParticipant(entity_ref="Valentin", role="actor")],
                    semantic_key=f"valentin:use:{change.object_ref.lower().replace(' ', '_')}",
                ),
            )

    async def _create_extraction_commitment(
        self, conn: Connection, commit, cycle: int
    ) -> UUID:
        """Create a narrative commitment from extraction"""
        commitment_id = await self.create_commitment(
            conn,
            commitment_type=commit.commitment_type.value,
            description=commit.description,
            cycle=cycle,
            deadline_cycle=commit.deadline_cycle,
        )

        if commit.commitment_type == CommitmentType.ARC and commit.objective:
            await self.create_commitment_arc(
                conn,
                commitment_id,
                objective=commit.objective,
                obstacle=commit.obstacle or "",
            )

        for entity_ref in commit.involved_entities:
            entity_id = self.registry.resolve(entity_ref)
            if entity_id:
                await self.add_commitment_entity(conn, commitment_id, entity_id)

        return commitment_id

    async def _resolve_extraction_commitment(
        self, conn: Connection, resolution, cycle: int
    ) -> None:
        """Resolve a commitment by description match"""
        reader = self._get_reader()
        commitment = await reader.find_commitment_by_description(
            conn, resolution.commitment_description
        )

        if commitment:
            # Create resolution fact
            from schema import FactData

            fact = FactData(
                cycle=cycle,
                fact_type=FactType.STATE_CHANGE,
                description=resolution.resolution_description,
                importance=3,
                participants=[],
                semantic_key=f"commitment:resolved:{commitment['id']}",
            )
            fact_id = await self.create_fact(conn, fact)

            await self.resolve_commitment(conn, commitment["id"], fact_id)

    async def _schedule_extraction_event(
        self, conn: Connection, event, source_cycle: int
    ) -> UUID:
        """Schedule a future event from extraction"""
        event_id = await self.create_event(
            conn,
            event_type=event.event_type,
            title=event.title,
            planned_cycle=event.planned_cycle,
            description=event.description,
            time=event.time,
            location_ref=event.location_ref,
            recurrence=event.recurrence,
            amount=event.amount,
        )

        for participant_ref in event.participants:
            entity_id = self.registry.resolve(participant_ref)
            if entity_id:
                await self.add_event_participant(conn, event_id, entity_id)

        return event_id
