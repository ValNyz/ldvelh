"""
LDVELH - Specialized Populators
WorldPopulator: Initial world generation
ExtractionPopulator: Narrative extraction processing
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from schema import (
    ArrivalEventData,
    CommitmentCreation,
    CommitmentType,
    EntityCreation,
    EntityType,
    EntityUpdate,
    FactDomain,
    FactType,
    InventoryChange,
    LocationData,
    NarrativeArcData,
    NarrativeExtraction,
    OrganizationData,
    RelationType,
    WorldData,
    WorldGeneration,
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

    async def populate(self, world_gen: WorldGeneration) -> UUID:
        """Main entry point - creates game and populates everything"""

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 1. Create game
                await self.create_game(conn, world_gen.world.name)

                # 2. Create world as top-level location
                await self._create_world(conn, world_gen.world)

                # 3. Create protagonist
                await self.create_protagonist(conn, world_gen.protagonist)

                # 4. Create AI
                await self.create_ai(
                    conn, world_gen.personal_ai, world_gen.protagonist.name
                )

                # 5. Create organizations (before locations for HQ refs)
                for org in world_gen.organizations:
                    await self.create_organization(conn, org)

                # 6. Create locations (two passes for parent refs)
                await self._create_locations_two_pass(conn, world_gen.locations)

                # 7. Update organization HQ refs now that locations exist
                await self._update_org_headquarters(conn, world_gen.organizations)

                # 8. Create characters
                for char in world_gen.characters:
                    await self.create_character(conn, char)

                # 9. Create inventory (with protagonist ownership)
                for obj in world_gen.inventory:
                    await self.create_object(
                        conn, obj, owner_ref=world_gen.protagonist.name
                    )

                # 10. Create all explicit relations
                for rel in world_gen.initial_relations:
                    await self.create_relation(conn, rel)

                # 11. Create narrative arcs as commitments
                for arc in world_gen.narrative_arcs:
                    await self._create_narrative_arc(conn, arc)

                # 12. Store arrival event metadata
                await self._store_arrival_event(conn, world_gen.arrival_event)

                # 13. Store generation metadata
                await self._store_generation_meta(conn, world_gen)

                logger.info(
                    f"World populated: {len(self.registry._by_name)} entities, game_id={self.game_id}"
                )

        return self.game_id

    async def _create_world(self, conn: Connection, world: WorldData) -> UUID:
        """Create the station as top-level location entity"""
        entity_id = await self.upsert_entity(conn, EntityType.LOCATION, world.name)

        await conn.execute(
            """INSERT INTO entity_locations (entity_id, location_type, accessible)
               VALUES ($1, $2, $3)
               ON CONFLICT (entity_id) DO UPDATE SET
                 location_type = EXCLUDED.location_type""",
            entity_id,
            world.station_type,
            True,
        )

        await self.set_attributes(
            conn,
            entity_id,
            {
                "population": world.population,
                "atmosphere": world.atmosphere,
                "description": world.description,
                "sectors": world.sectors,
                "founding_cycle": world.founding_cycle,
            },
        )

        return entity_id

    async def _create_locations_two_pass(
        self, conn: Connection, locations: list[LocationData]
    ) -> None:
        """Create locations in two passes to handle parent refs"""
        # Pass 1: Create all without parent refs
        for loc in locations:
            await self.upsert_entity(conn, EntityType.LOCATION, loc.name)

        # Pass 2: Full creation with parent refs resolved
        for loc in locations:
            await self.create_location(conn, loc)

    async def _update_org_headquarters(
        self, conn: Connection, organizations: list[OrganizationData]
    ) -> None:
        """Update organization HQ refs now that locations exist"""
        for org in organizations:
            if org.headquarters_ref:
                hq_id = self.registry.resolve(org.headquarters_ref)
                org_id = self.registry.resolve(org.name)
                if hq_id and org_id:
                    await conn.execute(
                        """UPDATE entity_organizations 
                           SET headquarters_id = $1 
                           WHERE entity_id = $2""",
                        hq_id,
                        org_id,
                    )

    async def _create_narrative_arc(
        self, conn: Connection, arc: NarrativeArcData
    ) -> UUID:
        """Create a narrative arc as a commitment"""
        commitment_id = await conn.fetchval(
            """INSERT INTO commitments 
               (game_id, type, description, created_cycle, deadline_cycle)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            self.game_id,
            arc.arc_type.value,
            f"{arc.title}: {arc.description}",
            1,
            arc.deadline_cycle,
        )

        # Add arc details if it's an 'arc' type
        if arc.arc_type == CommitmentType.ARC:
            await conn.execute(
                """INSERT INTO commitment_arcs (commitment_id, objective, obstacle)
                   VALUES ($1, $2, $3)""",
                commitment_id,
                arc.title,
                arc.stakes,
            )

        # Link involved entities
        for entity_name in arc.involved_entities:
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

    async def _store_arrival_event(
        self, conn: Connection, arrival: ArrivalEventData
    ) -> None:
        """Store arrival event for the narrator"""
        location_id = self.registry.resolve(arrival.arrival_location_ref)

        # Create arrival fact
        await conn.execute(
            """SELECT create_fact($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
            self.game_id,
            1,
            "incident",
            f"Arrivée sur la station via {arrival.arrival_method}. {arrival.optional_incident or ''}",
            "exploration",
            location_id,
            arrival.time_of_day.value,
            4,
            json.dumps([{"name": "Valentin", "role": "actor"}]),
        )

        # Create cycle summary with arrival metadata - INCLURE LA DATE
        await conn.execute(
            """INSERT INTO cycle_summaries 
               (game_id, cycle, day, date, summary, key_events)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            self.game_id,
            1,
            arrival.arrival_date.split()[0],
            arrival.arrival_date,  # ← AJOUTER LA DATE ICI
            f"Jour 1: Arrivée. Humeur: {arrival.initial_mood}",
            json.dumps(
                {
                    "arrival_method": arrival.arrival_method,
                    "arrival_location": arrival.arrival_location_ref,
                    "sensory_details": arrival.immediate_sensory_details,
                    "immediate_need": arrival.immediate_need,
                    "first_npc": arrival.first_npc_encountered,
                }
            ),
        )

    async def _store_generation_meta(
        self, conn: Connection, world_gen: WorldGeneration
    ) -> None:
        """Store generation metadata for reference"""
        # Store as game attributes
        await conn.execute(
            """UPDATE games SET updated_at = NOW() WHERE id = $1""", self.game_id
        )

        # Create extraction log for initial generation
        await conn.execute(
            """INSERT INTO extraction_logs 
               (game_id, cycle, entities_created, relations_created)
               VALUES ($1, $2, $3, $4)""",
            self.game_id,
            0,
            len(self.registry._by_name),
            len(world_gen.initial_relations),
        )


# =============================================================================
# NARRATIVE EXTRACTION POPULATOR
# =============================================================================


class ExtractionPopulator(KnowledgeGraphPopulator):
    """
    Specialized populator for processing narrative extractions.
    Call after each narrative generation to update the KG.
    """

    async def process_extraction(self, extraction: NarrativeExtraction) -> dict:
        """
        Process a complete narrative extraction.
        Returns stats about what was processed.
        """
        stats = {
            "facts_created": 0,
            "entities_created": 0,
            "entities_updated": 0,
            "relations_created": 0,
            "relations_ended": 0,
            "gauges_changed": 0,
            "credits_changed": 0,
            "beliefs_updated": 0,
            "commitments_created": 0,
            "errors": [],
        }

        cycle = extraction.cycle

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Ensure registry is loaded
                if not self.registry._by_name:
                    await self.load_registry(conn)

                # 1. Create new entities first (so refs work)
                for entity in extraction.entities_created:
                    try:
                        await self._process_entity_creation(conn, entity, cycle)
                        stats["entities_created"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Entity creation: {e}")

                # 2. Process entity updates
                for update in extraction.entities_updated:
                    try:
                        await self._process_entity_update(conn, update, cycle)
                        stats["entities_updated"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Entity update: {e}")

                # 3. Process entity removals
                for removal in extraction.entities_removed:
                    await self.remove_entity(
                        conn, removal.entity_ref, removal.cycle, removal.reason
                    )

                # 4. Create facts
                for fact in extraction.facts:
                    await self.create_fact(conn, fact)
                    stats["facts_created"] += 1

                # 5. Create new relations
                for rel_creation in extraction.relations_created:
                    result = await self.create_relation(
                        conn, rel_creation.relation, rel_creation.cycle
                    )
                    if result:
                        stats["relations_created"] += 1

                # 6. End relations
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

                # 7. Process gauge changes
                for gauge in extraction.gauge_changes:
                    success, old, new = await self.update_gauge(
                        conn, gauge.gauge, gauge.delta, cycle
                    )
                    if success:
                        stats["gauges_changed"] += 1

                # 8. Process credit transactions
                for tx in extraction.credit_transactions:
                    success, balance, error = await self.credit_transaction(
                        conn, tx.amount, cycle, tx.description
                    )
                    if success:
                        stats["credits_changed"] += 1
                    elif error:
                        stats["errors"].append(f"Credits: {error}")

                # 9. Process inventory changes
                for inv in extraction.inventory_changes:
                    await self._process_inventory_change(conn, inv, cycle)

                # 10. Update beliefs
                for belief in extraction.beliefs_updated:
                    await self.set_belief(conn, belief, cycle)
                    stats["beliefs_updated"] += 1

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
        """Process a new entity creation"""
        if creation.entity_type == EntityType.CHARACTER:
            return await self.create_character(conn, creation.character_data, cycle)
        elif creation.entity_type == EntityType.LOCATION:
            return await self.create_location(conn, creation.location_data, cycle)
        elif creation.entity_type == EntityType.OBJECT:
            return await self.create_object(conn, creation.object_data, cycle=cycle)
        elif creation.entity_type == EntityType.ORGANIZATION:
            return await self.create_organization(
                conn, creation.organization_data, cycle
            )
        else:
            # Generic entity
            return await self.upsert_entity(
                conn,
                creation.entity_type,
                creation.name,
                creation.aliases,
                cycle,
                creation.confirmed,
            )

    async def _process_entity_update(
        self, conn: Connection, update: EntityUpdate, cycle: int
    ) -> None:
        """Process an entity update"""
        entity_id = self.registry.resolve(update.entity_ref)
        if not entity_id:
            raise KeyError(f"Entity not found: {update.entity_ref}")

        # Add new aliases
        if update.new_aliases:
            await conn.execute(
                """UPDATE entities SET 
                   aliases = ARRAY(SELECT DISTINCT unnest(aliases || $1)),
                   updated_at = NOW()
                   WHERE id = $2""",
                update.new_aliases,
                entity_id,
            )

        # Update attributes
        for attr in update.attributes_changed:
            value = attr.value
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            await conn.execute(
                "SELECT set_attribute($1, $2, $3, $4, $5, $6)",
                self.game_id,
                entity_id,
                attr.key,
                str(value),
                cycle,
                json.dumps(attr.details) if attr.details else None,
            )

        # Update skills
        for skill in update.skills_changed:
            await self.set_skill(conn, entity_id, skill, cycle)

        # Update character arcs
        if update.arc_updates:
            arcs_json = json.dumps([arc.model_dump() for arc in update.arc_updates])
            await conn.execute(
                "SELECT set_attribute($1, $2, $3, $4, $5, $6)",
                self.game_id,
                entity_id,
                "arcs",
                arcs_json,
                cycle,
                None,
            )

    async def _process_inventory_change(
        self, conn: Connection, change: InventoryChange, cycle: int
    ) -> None:
        """Process an inventory change"""
        protagonist_ids = self.registry.get_by_type(EntityType.PROTAGONIST)
        if not protagonist_ids:
            return
        protagonist_id = protagonist_ids[0]

        if change.action == "acquire":
            if change.new_object:
                await self.create_object(
                    conn,
                    change.new_object,
                    owner_ref=self.registry.get_name(protagonist_id),
                    cycle=cycle,
                )

        elif change.action == "lose" and change.object_ref:
            object_id = self.registry.resolve(change.object_ref)
            if object_id:
                await self.end_relation(
                    conn,
                    self.registry.get_name(protagonist_id),
                    change.object_ref,
                    RelationType.OWNS,
                    cycle,
                    change.reason,
                )

        elif change.action == "use" and change.object_ref:
            # Create fact about using the object
            from schema.base import FactData, FactParticipant

            await self.create_fact(
                conn,
                FactData(
                    cycle=cycle,
                    fact_type=FactType.ACTION,
                    domain=FactDomain.PERSONAL,
                    description=f"Utilise {change.object_ref}. {change.reason or ''}",
                    importance=2,
                    participants=[FactParticipant(entity_ref="Valentin", role="actor")],
                ),
            )

    async def _create_commitment(
        self, conn: Connection, commit: CommitmentCreation, cycle: int
    ) -> UUID:
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
        # Find commitment by description similarity
        commitment = await conn.fetchrow(
            """SELECT id FROM commitments 
               WHERE game_id = $1 AND resolved = false
               AND description ILIKE '%' || $2 || '%'
               ORDER BY created_cycle DESC LIMIT 1""",
            self.game_id,
            resolution.commitment_description[:50],
        )

        if commitment:
            # Create resolution fact
            fact_id = await conn.fetchval(
                """SELECT create_fact($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                self.game_id,
                cycle,
                "incident",
                resolution.resolution_description,
                "other",
                None,
                None,
                3,
                "[]",
            )

            await conn.execute(
                """UPDATE commitments SET 
                   resolved = true, resolution_fact_id = $1
                   WHERE id = $2""",
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
               (game_id, type, title, description, planned_cycle, moment, 
                location_id, recurrence, amount)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING id""",
            self.game_id,
            event.event_type,
            event.title,
            event.description,
            event.planned_cycle,
            event.moment.value if event.moment else None,
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
        """Log the extraction for debugging/analysis"""
        await conn.execute(
            """INSERT INTO extraction_logs 
               (game_id, cycle, entities_created, relations_created,
                facts_created, attributes_modified, errors)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            self.game_id,
            extraction.cycle,
            stats["entities_created"],
            stats["relations_created"],
            stats["facts_created"],
            stats["entities_updated"],
            json.dumps(stats["errors"]) if stats["errors"] else None,
        )

        # Store cycle summary
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
