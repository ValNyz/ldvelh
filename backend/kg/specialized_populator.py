"""
LDVELH - Specialized Populators (EAV Architecture)
WorldPopulator: Initial world generation processing
ExtractionPopulator: Narrative extraction processing
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from schema import (
    AttributeKey,
    AttributeWithVisibility,
    CommitmentType,
    EntityCreation,
    EntityType,
    EntityUpdate,
    FactType,
    InventoryChange,
    NarrativeExtraction,
    ObjectCreation,
    RelationData,
    RelationType,
)

from .populator import KnowledgeGraphPopulator

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
                    await conn.execute(
                        "UPDATE games SET name = $1, updated_at = NOW() WHERE id = $2",
                        world_gen.world.name,
                        self.game_id,
                    )
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
                protagonist_name = world_gen.protagonist.name
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
                    await conn.execute(
                        "UPDATE entity_organizations SET headquarters_id = $1 WHERE entity_id = $2",
                        hq_id,
                        org_id,
                    )

    async def _create_narrative_arc(self, conn: Connection, arc) -> UUID:
        """Create a narrative arc as a commitment"""
        commitment_id = await conn.fetchval(
            """INSERT INTO commitments 
               (game_id, type, description, created_cycle, deadline_cycle)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            self.game_id,
            arc.arc_type.value if hasattr(arc.arc_type, "value") else arc.arc_type,
            f"{arc.title}: {arc.description}",
            1,
            arc.deadline_cycle if hasattr(arc, "deadline_cycle") else None,
        )

        if hasattr(arc, "arc_type") and arc.arc_type == CommitmentType.ARC:
            await conn.execute(
                """INSERT INTO commitment_arcs (commitment_id, objective, obstacle)
                   VALUES ($1, $2, $3)""",
                commitment_id,
                arc.title,
                arc.stakes if hasattr(arc, "stakes") else "",
            )

        for entity_name in (
            arc.involved_entities if hasattr(arc, "involved_entities") else []
        ):
            entity_id = self.registry.resolve(entity_name)
            if entity_id:
                await conn.execute(
                    """INSERT INTO commitment_entities (commitment_id, entity_id, role)
                       VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
                    commitment_id,
                    entity_id,
                    "involved",
                )

        return commitment_id

    async def _store_arrival_event(self, conn: Connection, arrival) -> None:
        """Store arrival event for the narrator"""
        location_id = self.registry.resolve(arrival.arrival_location_ref)

        await conn.execute(
            "SELECT create_fact($1, $2, $3::fact_type, $4, $5, $6, $7, $8::jsonb)",
            self.game_id,
            1,
            "encounter",
            f"Arrivée sur la station via {arrival.arrival_method}. {arrival.optional_incident or ''}",
            location_id,
            arrival.time if hasattr(arrival, "time") else None,
            4,
            json.dumps([{"name": "Valentin", "role": "actor"}]),
        )

        await conn.execute(
            """INSERT INTO cycle_summaries 
               (game_id, cycle, date, summary, key_events)
               VALUES ($1, $2, $3, $4, $5)""",
            self.game_id,
            1,
            arrival.arrival_date,
            f"Jour 1: Arrivée. Humeur: {arrival.initial_mood}",
            json.dumps(
                {
                    "arrival_method": arrival.arrival_method,
                    "arrival_location": arrival.arrival_location_ref,
                }
            ),
        )

    async def _store_generation_meta(self, conn: Connection, world_gen) -> None:
        """Store generation metadata"""
        await conn.execute(
            "UPDATE games SET updated_at = NOW() WHERE id = $1",
            self.game_id,
        )

        await conn.execute(
            """INSERT INTO extraction_logs 
               (game_id, cycle, entities_created, relations_created)
               VALUES ($1, $2, $3, $4)""",
            self.game_id,
            0,
            len(self.registry._by_name),
            len(world_gen.initial_relations)
            if hasattr(world_gen, "initial_relations")
            else 0,
        )


# =============================================================================
# NARRATIVE EXTRACTION POPULATOR
# =============================================================================


class ExtractionPopulator(KnowledgeGraphPopulator):
    """
    Specialized populator for processing narrative extractions.
    Uses unified EAV format for all entity types.
    """

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
                    await self._create_commitment(conn, commit, cycle)
                    stats["commitments_created"] += 1

                # 12. Resolve commitments
                for resolution in extraction.commitments_resolved:
                    await self._resolve_commitment(conn, resolution, cycle)

                # 13. Schedule events
                for event in extraction.events_scheduled:
                    await self._schedule_event(conn, event, cycle)

                # 14. Store extraction log
                await self._log_extraction(conn, extraction, stats)

        return stats

    async def _process_entity_creation(
        self, conn: Connection, creation: EntityCreation, cycle: int
    ) -> UUID:
        """
        Process a new entity creation using unified EAV format.
        All entity types use attributes list.
        """
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

        # Handle FK references
        if creation.entity_type == EntityType.LOCATION and creation.parent_location_ref:
            parent_id = self.registry.resolve(creation.parent_location_ref)
            if parent_id:
                await conn.execute(
                    "UPDATE entity_locations SET parent_location_id = $1 WHERE entity_id = $2",
                    parent_id,
                    entity_id,
                )

        if (
            creation.entity_type == EntityType.ORGANIZATION
            and creation.headquarters_ref
        ):
            hq_id = self.registry.resolve(creation.headquarters_ref)
            if hq_id:
                await conn.execute(
                    "UPDATE entity_organizations SET headquarters_id = $1 WHERE entity_id = $2",
                    hq_id,
                    entity_id,
                )

        if creation.entity_type == EntityType.AI and creation.creator_ref:
            creator_id = self.registry.resolve(creation.creator_ref)
            if creator_id:
                await conn.execute(
                    "UPDATE entity_ais SET creator_id = $1 WHERE entity_id = $2",
                    creator_id,
                    entity_id,
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
        """
        Process an object creation from inventory acquisition.
        Creates the object AND the owns relation automatically.
        """
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
            await conn.execute(
                """UPDATE entities SET 
                   aliases = ARRAY(SELECT DISTINCT unnest(aliases || $1)),
                   updated_at = NOW()
                   WHERE id = $2""",
                update.new_aliases,
                entity_id,
            )

        # Update known status
        if update.now_known:
            await conn.execute(
                "UPDATE entities SET known_by_protagonist = true, updated_at = NOW() WHERE id = $1",
                entity_id,
            )
            if update.real_name:
                await conn.execute(
                    "UPDATE entities SET name = $1, updated_at = NOW() WHERE id = $2",
                    update.real_name,
                    entity_id,
                )

        # Update attributes
        if update.attributes_changed:
            entity_type = await self._get_entity_type(conn, entity_id)
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

    async def _create_commitment(self, conn: Connection, commit, cycle: int) -> UUID:
        """Create a narrative commitment"""
        commitment_id = await conn.fetchval(
            """INSERT INTO commitments 
               (game_id, type, description, created_cycle, deadline_cycle)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            self.game_id,
            commit.commitment_type.value,
            commit.description,
            cycle,
            commit.deadline_cycle,
        )

        if commit.commitment_type == CommitmentType.ARC and commit.objective:
            await conn.execute(
                """INSERT INTO commitment_arcs (commitment_id, objective, obstacle)
                   VALUES ($1, $2, $3)""",
                commitment_id,
                commit.objective,
                commit.obstacle or "",
            )

        for entity_ref in commit.involved_entities:
            entity_id = self.registry.resolve(entity_ref)
            if entity_id:
                await conn.execute(
                    """INSERT INTO commitment_entities (commitment_id, entity_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                    commitment_id,
                    entity_id,
                )

        return commitment_id

    async def _resolve_commitment(
        self, conn: Connection, resolution, cycle: int
    ) -> None:
        """Resolve a commitment by description match"""
        commitment = await conn.fetchrow(
            """SELECT id FROM commitments 
               WHERE game_id = $1 AND resolved = false
               AND description ILIKE '%' || $2 || '%'
               ORDER BY created_cycle DESC LIMIT 1""",
            self.game_id,
            resolution.commitment_description[:50],
        )

        if commitment:
            fact_id = await conn.fetchval(
                "SELECT create_fact($1, $2, $3::fact_type, $4, $5, $6, $7, $8::jsonb, $9)",
                self.game_id,
                cycle,
                "state_change",
                resolution.resolution_description,
                None,
                None,
                3,
                "[]",
                None,
            )

            await conn.execute(
                "UPDATE commitments SET resolved = true, resolution_fact_id = $1 WHERE id = $2",
                fact_id,
                commitment["id"],
            )

    async def _schedule_event(self, conn: Connection, event, source_cycle: int) -> UUID:
        """Schedule a future event"""
        location_id = None
        if event.location_ref:
            location_id = self.registry.resolve(event.location_ref)

        event_id = await conn.fetchval(
            """INSERT INTO events 
               (game_id, type, title, description, planned_cycle, time, 
                location_id, recurrence, amount)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
            self.game_id,
            event.event_type,
            event.title,
            event.description,
            event.planned_cycle,
            event.time,
            location_id,
            json.dumps(event.recurrence) if event.recurrence else None,
            event.amount,
        )

        for participant_ref in event.participants:
            entity_id = self.registry.resolve(participant_ref)
            if entity_id:
                await conn.execute(
                    """INSERT INTO event_participants (event_id, entity_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                    event_id,
                    entity_id,
                )

        return event_id

    async def _log_extraction(
        self, conn: Connection, extraction: NarrativeExtraction, stats: dict
    ) -> None:
        """Log the extraction"""
        await conn.execute(
            """INSERT INTO extraction_logs 
               (game_id, cycle, entities_created, relations_created,
                facts_created, attributes_modified, errors)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            self.game_id,
            extraction.cycle,
            stats["entities_created"] + stats["objects_created"],
            stats["relations_created"],
            stats["facts_created"],
            stats["entities_updated"],
            json.dumps(stats["errors"]) if stats["errors"] else None,
        )

        await conn.execute(
            """INSERT INTO cycle_summaries (game_id, cycle, summary, key_events)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (game_id, cycle) DO UPDATE SET
                 summary = EXCLUDED.summary,
                 key_events = EXCLUDED.key_events""",
            self.game_id,
            extraction.cycle,
            extraction.segment_summary,
            json.dumps({"npcs_present": extraction.key_npcs_present}),
        )
