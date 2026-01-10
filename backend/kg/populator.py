"""
LDVELH - Knowledge Graph Populator
Réutilisable pour génération initiale ET extraction narrative
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from schema import (
    OWNERSHIP_RELATIONS,
    PROFESSIONAL_RELATIONS,
    SOCIAL_RELATIONS,
    SPATIAL_RELATIONS,
    BeliefData,
    CharacterData,
    # Core
    EntityType,
    # Narrative
    FactData,
    LocationData,
    ObjectData,
    OrganizationData,
    PersonalAIData,
    # Entities
    ProtagonistData,
    # Relations
    RelationData,
    RelationType,
    Skill,
)

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)


# =============================================================================
# ENTITY REGISTRY
# =============================================================================


@dataclass
class EntityRegistry:
    """
    Tracks entity name → UUID mappings.
    Shared across populator operations for reference resolution.
    """

    _by_name: dict[str, UUID] = field(default_factory=dict)
    _by_type: dict[EntityType, list[UUID]] = field(
        default_factory=lambda: {t: [] for t in EntityType}
    )
    _names_by_id: dict[UUID, str] = field(default_factory=dict)

    def register(self, name: str, entity_id: UUID, entity_type: EntityType) -> None:
        key = name.lower().strip()
        self._by_name[key] = entity_id
        self._by_type[entity_type].append(entity_id)
        self._names_by_id[entity_id] = name

    def resolve(self, name: str) -> UUID | None:
        return self._by_name.get(name.lower().strip())

    def resolve_strict(self, name: str) -> UUID:
        result = self.resolve(name)
        if result is None:
            raise KeyError(f"Entity not found: '{name}'")
        return result

    def get_by_type(self, entity_type: EntityType) -> list[UUID]:
        return self._by_type[entity_type].copy()

    def get_name(self, entity_id: UUID) -> str | None:
        return self._names_by_id.get(entity_id)

    def __contains__(self, name: str) -> bool:
        return name.lower().strip() in self._by_name


# =============================================================================
# BASE POPULATOR
# =============================================================================


class KnowledgeGraphPopulator:
    """
    Core populator with reusable methods for all entity types.
    Use directly or subclass for specific use cases.
    """

    def __init__(self, pool: Pool, game_id: UUID | None = None):
        self.pool = pool
        self.game_id = game_id
        self.registry = EntityRegistry()

    # =========================================================================
    # GAME MANAGEMENT
    # =========================================================================

    async def create_game(self, conn: Connection, name: str) -> UUID:
        """Create a new game and set it as current"""
        self.game_id = await conn.fetchval(
            "INSERT INTO games (name) VALUES ($1) RETURNING id", name
        )
        logger.info(f"Created game {self.game_id}: {name}")
        return self.game_id

    async def load_registry(self, conn: Connection) -> None:
        """Load existing entities into registry (for continuing a game)"""
        if not self.game_id:
            raise ValueError("game_id must be set before loading registry")

        rows = await conn.fetch(
            "SELECT id, name, type FROM entities WHERE game_id = $1 AND removed_cycle IS NULL",
            self.game_id,
        )
        for row in rows:
            self.registry.register(row["name"], row["id"], EntityType(row["type"]))

        logger.info(f"Loaded {len(rows)} entities into registry")

    # =========================================================================
    # ENTITY CREATION - GENERIC
    # =========================================================================

    async def upsert_entity(
        self,
        conn: Connection,
        entity_type: EntityType,
        name: str,
        aliases: list[str] | None = None,
        cycle: int = 1,
        confirmed: bool = True,
    ) -> UUID:
        """Create or update an entity, register it, return ID"""
        entity_id = await conn.fetchval(
            "SELECT upsert_entity($1, $2, $3, $4, $5, $6)",
            self.game_id,
            entity_type.value,
            name,
            aliases or [],
            cycle,
            confirmed,
        )
        self.registry.register(name, entity_id, entity_type)
        return entity_id

    async def set_attributes(
        self,
        conn: Connection,
        entity_id: UUID,
        attrs: dict[str, str | int | float | list | dict],
        cycle: int = 1,
    ) -> None:
        """Set multiple attributes on an entity"""
        for key, value in attrs.items():
            # Convert complex types to JSON string
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            elif not isinstance(value, str):
                value = str(value)

            await conn.execute(
                "SELECT set_attribute($1, $2, $3, $4, $5, $6)",
                self.game_id,
                entity_id,
                key,
                value,
                cycle,
                None,
            )

    async def set_skill(
        self, conn: Connection, entity_id: UUID, skill: Skill, cycle: int = 1
    ) -> UUID | None:
        """Set a skill on an entity"""
        return await conn.fetchval(
            "SELECT set_skill($1, $2, $3, $4, $5)",
            self.game_id,
            entity_id,
            skill.name,
            skill.level,
            cycle,
        )

    async def remove_entity(
        self, conn: Connection, entity_ref: str, cycle: int, reason: str
    ) -> bool:
        """Mark an entity as removed"""
        entity_id = self.registry.resolve(entity_ref)
        if not entity_id:
            logger.warning(f"Cannot remove unknown entity: {entity_ref}")
            return False

        await conn.execute(
            """UPDATE entities 
               SET removed_cycle = $1, removal_reason = $2, updated_at = NOW()
               WHERE id = $3""",
            cycle,
            reason,
            entity_id,
        )
        return True

    # =========================================================================
    # TYPED ENTITY CREATION
    # =========================================================================

    async def create_protagonist(
        self, conn: Connection, data: ProtagonistData, cycle: int = 1
    ) -> UUID:
        """Create the protagonist entity"""
        entity_id = await self.upsert_entity(
            conn, EntityType.PROTAGONIST, data.name, cycle=cycle
        )

        await conn.execute(
            """INSERT INTO entity_protagonists 
               (entity_id, origin_location, departure_reason, backstory)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (entity_id) DO UPDATE SET
                 origin_location = EXCLUDED.origin_location,
                 departure_reason = EXCLUDED.departure_reason,
                 backstory = EXCLUDED.backstory""",
            entity_id,
            data.origin_location,
            data.departure_story,
            data.backstory,
        )

        await self.set_attributes(
            conn,
            entity_id,
            {
                "credits": data.initial_credits,
                "energy": data.initial_energy,
                "morale": data.initial_morale,
                "health": data.initial_health,
                "hobbies": data.hobbies,
                "departure_reason": data.departure_reason.value,
            },
            cycle,
        )

        for skill in data.skills:
            await self.set_skill(conn, entity_id, skill, cycle)

        return entity_id

    async def create_character(
        self, conn: Connection, data: CharacterData, cycle: int = 1
    ) -> UUID:
        """Create a character (NPC) entity"""
        entity_id = await self.upsert_entity(
            conn, EntityType.CHARACTER, data.name, cycle=cycle
        )

        await conn.execute(
            """INSERT INTO entity_characters 
               (entity_id, species, gender, pronouns, station_arrival_cycle,
                origin_location, physical_description, traits)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (entity_id) DO UPDATE SET
                 species = EXCLUDED.species,
                 gender = EXCLUDED.gender,
                 pronouns = EXCLUDED.pronouns,
                 physical_description = EXCLUDED.physical_description,
                 traits = EXCLUDED.traits""",
            entity_id,
            data.species,
            data.gender,
            data.pronouns,
            data.station_arrival_cycle,
            data.origin_location,
            data.physical_description,
            json.dumps(data.personality_traits),
        )

        # Store arcs as attributes
        arcs_data = [arc.model_dump() for arc in data.arcs]
        attrs = {
            "occupation": data.occupation,
            "arcs": arcs_data,
            "romantic_potential": data.romantic_potential,
            "is_mandatory": data.is_mandatory,
        }
        if data.age:
            attrs["age"] = data.age

        await self.set_attributes(conn, entity_id, attrs, cycle)

        return entity_id

    async def create_location(
        self, conn: Connection, data: LocationData, cycle: int = 1
    ) -> UUID:
        """Create a location entity"""
        entity_id = await self.upsert_entity(
            conn, EntityType.LOCATION, data.name, cycle=cycle
        )

        parent_id = None
        if data.parent_location_ref:
            parent_id = self.registry.resolve(data.parent_location_ref)

        await conn.execute(
            """INSERT INTO entity_locations 
               (entity_id, location_type, sector, parent_location_id, accessible)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (entity_id) DO UPDATE SET
                 location_type = EXCLUDED.location_type,
                 sector = EXCLUDED.sector,
                 parent_location_id = EXCLUDED.parent_location_id,
                 accessible = EXCLUDED.accessible""",
            entity_id,
            data.location_type,
            data.sector,
            parent_id,
            data.accessible,
        )

        attrs = {
            "description": data.description,
            "atmosphere": data.atmosphere,
        }
        if data.notable_features:
            attrs["notable_features"] = data.notable_features
        if data.typical_crowd:
            attrs["typical_crowd"] = data.typical_crowd
        if data.operating_hours:
            attrs["operating_hours"] = data.operating_hours

        await self.set_attributes(conn, entity_id, attrs, cycle)

        return entity_id

    async def create_object(
        self,
        conn: Connection,
        data: ObjectData,
        owner_ref: str | None = None,
        cycle: int = 1,
    ) -> UUID:
        """Create an object entity, optionally with owner"""
        entity_id = await self.upsert_entity(
            conn, EntityType.OBJECT, data.name, cycle=cycle
        )

        await conn.execute(
            """INSERT INTO entity_objects 
               (entity_id, category, transportable, stackable, base_value)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (entity_id) DO UPDATE SET
                 category = EXCLUDED.category,
                 transportable = EXCLUDED.transportable,
                 stackable = EXCLUDED.stackable,
                 base_value = EXCLUDED.base_value""",
            entity_id,
            data.category,
            data.transportable,
            data.stackable,
            data.base_value,
        )

        attrs = {"description": data.description}
        if data.emotional_significance:
            attrs["emotional_significance"] = data.emotional_significance
        await self.set_attributes(conn, entity_id, attrs, cycle)

        # Create ownership relation if owner specified
        if owner_ref:
            owner_id = self.registry.resolve(owner_ref)
            if owner_id:
                rel_id = await self.create_relation(
                    conn,
                    RelationData(
                        source_ref=owner_ref,
                        target_ref=data.name,
                        relation_type=RelationType.OWNS,
                        quantity=data.quantity,
                        origin="initial",
                    ),
                    cycle,
                )

        return entity_id

    async def create_organization(
        self, conn: Connection, data: OrganizationData, cycle: int = 1
    ) -> UUID:
        """Create an organization entity"""
        entity_id = await self.upsert_entity(
            conn, EntityType.ORGANIZATION, data.name, cycle=cycle
        )

        hq_id = None
        if data.headquarters_ref:
            hq_id = self.registry.resolve(data.headquarters_ref)

        await conn.execute(
            """INSERT INTO entity_organizations 
               (entity_id, org_type, domain, size, founding_cycle, headquarters_id)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (entity_id) DO UPDATE SET
                 org_type = EXCLUDED.org_type,
                 domain = EXCLUDED.domain,
                 size = EXCLUDED.size""",
            entity_id,
            data.org_type,
            data.domain,
            data.size,
            data.founding_cycle,
            hq_id,
        )

        await self.set_attributes(
            conn,
            entity_id,
            {
                "description": data.description,
                "reputation": data.reputation,
                "is_employer": data.is_employer,
            },
            cycle,
        )

        return entity_id

    async def create_ai(
        self, conn: Connection, data: PersonalAIData, creator_ref: str, cycle: int = 1
    ) -> UUID:
        """Create a personal AI entity"""
        entity_id = await self.upsert_entity(
            conn, EntityType.AI, data.name, cycle=cycle
        )

        creator_id = self.registry.resolve(creator_ref)

        await conn.execute(
            """INSERT INTO entity_ais 
               (entity_id, creator_id, substrate, traits)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (entity_id) DO UPDATE SET
                 substrate = EXCLUDED.substrate,
                 traits = EXCLUDED.traits""",
            entity_id,
            creator_id,
            data.substrate,
            json.dumps(
                {
                    "voice": data.voice_description,
                    "personality": data.personality_traits,
                    "quirk": data.quirk,
                }
            ),
        )

        # Create ownership relation
        if creator_id:
            await self.create_relation(
                conn,
                RelationData(
                    source_ref=creator_ref,
                    target_ref=data.name,
                    relation_type=RelationType.OWNS,
                ),
                cycle,
            )

        return entity_id

    # =========================================================================
    # RELATIONS
    # =========================================================================

    async def create_relation(
        self, conn: Connection, data: RelationData, cycle: int = 1
    ) -> UUID | None:
        """Create or update a relation"""
        source_id = self.registry.resolve(data.source_ref)
        target_id = self.registry.resolve(data.target_ref)

        if not source_id or not target_id:
            logger.warning(
                f"Cannot create relation: {data.source_ref} -> {data.target_ref} (missing entity)"
            )
            return None

        rel_id = await conn.fetchval(
            "SELECT upsert_relation($1, $2, $3, $4, $5, $6, $7, $8)",
            self.game_id,
            source_id,
            target_id,
            data.relation_type.value,
            cycle,
            data.certainty.value,
            data.is_true,
            data.context,
        )

        # Handle typed relation data
        await self._insert_typed_relation_data(conn, rel_id, data)

        return rel_id

    async def _insert_typed_relation_data(
        self, conn: Connection, rel_id: UUID, data: RelationData
    ) -> None:
        """Insert into the appropriate typed relation table"""
        rt = data.relation_type

        # Social relations
        if rt in SOCIAL_RELATIONS:
            social = data.social
            if social or data.source_info:
                await conn.execute(
                    """INSERT INTO relations_social 
                       (relation_id, level, context, romantic_stage, family_bond)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (relation_id) DO UPDATE SET
                         level = COALESCE(EXCLUDED.level, relations_social.level),
                         context = COALESCE(EXCLUDED.context, relations_social.context),
                         romantic_stage = COALESCE(EXCLUDED.romantic_stage, relations_social.romantic_stage),
                         family_bond = COALESCE(EXCLUDED.family_bond, relations_social.family_bond)""",
                    rel_id,
                    social.level if social else None,
                    social.context if social else None,
                    social.romantic_stage if social else None,
                    social.family_bond if social else None,
                )

        # Professional relations
        elif rt in PROFESSIONAL_RELATIONS:
            prof = data.professional
            if prof:
                await conn.execute(
                    """INSERT INTO relations_professional 
                       (relation_id, position, position_start_cycle, part_time)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (relation_id) DO UPDATE SET
                         position = COALESCE(EXCLUDED.position, relations_professional.position),
                         position_start_cycle = COALESCE(EXCLUDED.position_start_cycle, relations_professional.position_start_cycle),
                         part_time = COALESCE(EXCLUDED.part_time, relations_professional.part_time)""",
                    rel_id,
                    prof.position,
                    prof.position_start_cycle,
                    prof.part_time,
                )

        # Spatial relations
        elif rt in SPATIAL_RELATIONS:
            spatial = data.spatial
            if spatial:
                await conn.execute(
                    """INSERT INTO relations_spatial (relation_id, regularity, time_of_day)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (relation_id) DO UPDATE SET
                         regularity = COALESCE(EXCLUDED.regularity, relations_spatial.regularity),
                         time_of_day = COALESCE(EXCLUDED.time_of_day, relations_spatial.time_of_day)""",
                    rel_id,
                    spatial.regularity,
                    spatial.time_of_day,
                )

        # Ownership relations
        elif rt in OWNERSHIP_RELATIONS:
            own = data.ownership
            await conn.execute(
                """INSERT INTO relations_ownership 
                   (relation_id, quantity, origin, amount, acquisition_cycle)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (relation_id) DO UPDATE SET
                     quantity = COALESCE(EXCLUDED.quantity, relations_ownership.quantity),
                     origin = COALESCE(EXCLUDED.origin, relations_ownership.origin),
                     amount = COALESCE(EXCLUDED.amount, relations_ownership.amount),
                     acquisition_cycle = COALESCE(EXCLUDED.acquisition_cycle, relations_ownership.acquisition_cycle)""",
                rel_id,
                own.quantity if own else 1,
                own.origin if own else None,
                own.amount if own else None,
                own.acquisition_cycle if own else None,
            )

    async def end_relation(
        self,
        conn: Connection,
        source_ref: str,
        target_ref: str,
        relation_type: RelationType,
        cycle: int,
        reason: str | None = None,
    ) -> bool:
        """End an existing relation"""
        result = await conn.fetchval(
            "SELECT end_relation($1, $2, $3, $4, $5, $6)",
            self.game_id,
            source_ref,
            target_ref,
            relation_type.value,
            cycle,
            reason,
        )
        return result

    # =========================================================================
    # FACTS
    # =========================================================================

    async def create_fact(self, conn: Connection, fact: FactData) -> UUID | None:
        """
        Crée un fait avec déduplication par semantic_key.
        Retourne None si le fait existe déjà (doublon).
        """
        # Vérifier si un fait avec cette semantic_key existe déjà pour ce cycle
        if fact.semantic_key:
            existing = await conn.fetchval(
                """
                SELECT id FROM facts 
                WHERE game_id = $1 AND cycle = $2 AND semantic_key = $3
                """,
                self.game_id,
                fact.cycle,
                fact.semantic_key,
            )
            if existing:
                logger.debug(f"[FACT] Doublon ignoré: {fact.semantic_key}")
                return None

        # Résoudre la location
        location_id = None
        if fact.location_ref:
            location_id = await self._resolve_entity(
                conn, fact.location_ref, "location"
            )

        # Préparer les participants
        participants_json = []
        for p in fact.participants:
            entity_id = await self._resolve_entity(conn, p.entity_ref)
            if entity_id:
                participants_json.append(
                    {
                        "name": p.entity_ref,
                        "role": p.role.value if hasattr(p.role, "value") else p.role,
                    }
                )

        # Créer le fait
        fact_id = await conn.fetchval(
            """
            SELECT create_fact(
                $1, $2, $3::fact_type, $4, 
                $5, $6, $7, $8::jsonb, $9
            )
            """,
            self.game_id,
            fact.cycle,
            fact.fact_type.value,
            fact.description,
            location_id,
            fact.time,
            fact.importance,
            json.dumps(participants_json),
            fact.semantic_key,
        )

        logger.info(
            f"[FACT] Créé: [{fact.fact_type.value}] {fact.semantic_key} (imp={fact.importance})"
        )
        return fact_id

    async def process_facts(self, conn: Connection, facts: list[FactData]) -> int:
        """
        Traite une liste de facts avec déduplication.
        Retourne le nombre de facts effectivement créés.
        """
        created = 0
        seen_keys = set()

        for fact in facts:
            # Déduplication locale (même batch)
            if fact.semantic_key in seen_keys:
                logger.debug(f"[FACT] Doublon local ignoré: {fact.semantic_key}")
                continue
            seen_keys.add(fact.semantic_key)

            # Création avec déduplication DB
            fact_id = await self.create_fact(conn, fact)
            if fact_id:
                created += 1

        logger.info(
            f"[FACTS] {created}/{len(facts)} facts créés (doublons ignorés: {len(facts) - created})"
        )
        return created

    # =========================================================================
    # BELIEFS
    # =========================================================================

    async def set_belief(
        self,
        conn: Connection,
        data: BeliefData,
        cycle: int,
        source_fact_id: UUID | None = None,
    ) -> UUID:
        """Set or update a belief"""
        subject_id = self.registry.resolve_strict(data.subject_ref)

        return await conn.fetchval(
            "SELECT set_belief($1, $2, $3, $4, $5, $6, $7, $8)",
            self.game_id,
            subject_id,
            data.key,
            data.content,
            cycle,
            data.is_true,
            data.certainty.value,
            source_fact_id,
        )

    # =========================================================================
    # PROTAGONIST SPECIFIC
    # =========================================================================

    async def update_gauge(
        self, conn: Connection, gauge: str, delta: float, cycle: int
    ) -> tuple[bool, float, float]:
        """Update energy/morale/health"""
        result = await conn.fetchrow(
            "SELECT * FROM update_gauge($1, $2, $3, $4)",
            self.game_id,
            gauge,
            delta,
            cycle,
        )
        return result["success"], result["old_value"], result["new_value"]

    async def credit_transaction(
        self, conn: Connection, amount: int, cycle: int, description: str | None = None
    ) -> tuple[bool, int, str | None]:
        """Add or remove credits"""
        result = await conn.fetchrow(
            "SELECT * FROM credit_transaction($1, $2, $3, $4)",
            self.game_id,
            amount,
            cycle,
            description,
        )
        return result["success"], result["new_balance"], result["error"]

    # =========================================================================
    # CHAT MESSAGES
    # =========================================================================

    async def save_message(
        self,
        conn: Connection,
        role: str,
        content: str,
        cycle: int,
        day: int | None = None,
        date: str | None = None,
        location_ref: str | None = None,
        npcs_present: list[str] | None = None,
        summary: str | None = None,
        state_snapshot: dict | None = None,
    ) -> UUID:
        """Save a chat message"""
        location_id = self.registry.resolve(location_ref) if location_ref else None

        # Resolve NPC refs to UUIDs
        npc_ids = []
        if npcs_present:
            for npc_ref in npcs_present:
                npc_id = self.registry.resolve(npc_ref)
                if npc_id:
                    npc_ids.append(npc_id)

        return await conn.fetchval(
            """INSERT INTO chat_messages 
               (game_id, role, content, cycle, day, date, location_id, 
                npcs_present, summary, state_snapshot)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING id""",
            self.game_id,
            role,
            content,
            cycle,
            day,
            date,
            location_id,
            npc_ids,
            summary,
            json.dumps(state_snapshot) if state_snapshot else None,
        )

    async def get_message(self, conn: Connection, message_id: UUID) -> dict | None:
        """Get a single message by ID"""
        row = await conn.fetchrow(
            "SELECT * FROM chat_messages WHERE id = $1 AND game_id = $2",
            message_id,
            self.game_id,
        )
        return dict(row) if row else None

    async def get_messages_since(
        self, conn: Connection, since_cycle: int, limit: int = 100
    ) -> list[dict]:
        """Get messages from a cycle onwards"""
        rows = await conn.fetch(
            """SELECT * FROM chat_messages 
               WHERE game_id = $1 AND cycle >= $2
               ORDER BY created_at ASC
               LIMIT $3""",
            self.game_id,
            since_cycle,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_recent_messages(
        self, conn: Connection, limit: int = 20
    ) -> list[dict]:
        """Get the most recent messages"""
        rows = await conn.fetch(
            """SELECT * FROM chat_messages 
               WHERE game_id = $1
               ORDER BY created_at DESC
               LIMIT $2""",
            self.game_id,
            limit,
        )
        return [dict(row) for row in reversed(rows)]

    # =========================================================================
    # CYCLE SUMMARIES
    # =========================================================================

    async def save_cycle_summary(
        self,
        conn: Connection,
        cycle: int,
        summary: str,
        day: int | None = None,
        date: str | None = None,
        key_events: dict | None = None,
        modified_relations: dict | None = None,
    ) -> UUID:
        """Save or update a cycle summary"""
        return await conn.fetchval(
            """INSERT INTO cycle_summaries 
               (game_id, cycle, day, date, summary, key_events, modified_relations)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (game_id, cycle) DO UPDATE SET
                 day = COALESCE(EXCLUDED.day, cycle_summaries.day),
                 date = COALESCE(EXCLUDED.date, cycle_summaries.date),
                 summary = EXCLUDED.summary,
                 key_events = COALESCE(EXCLUDED.key_events, cycle_summaries.key_events),
                 modified_relations = COALESCE(EXCLUDED.modified_relations, cycle_summaries.modified_relations)
               RETURNING id""",
            self.game_id,
            cycle,
            day,
            date,
            summary,
            json.dumps(key_events) if key_events else None,
            json.dumps(modified_relations) if modified_relations else None,
        )

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_message(
        self, conn: Connection, message_id: UUID, include_message: bool = False
    ) -> dict:
        """
        Rollback the game state to just before (or at) a specific message.

        Args:
            message_id: The message to rollback to
            include_message: If True, keep this message. If False, delete it too.

        Returns:
            Stats about what was rolled back
        """
        # Get the message
        message = await self.get_message(conn, message_id)
        if not message:
            raise ValueError(f"Message {message_id} not found")

        target_cycle = message["cycle"]
        message_created_at = message["created_at"]

        # If we want to include the message, we rollback to its cycle
        # If we want to exclude it, we rollback to cycle - 1
        rollback_cycle = target_cycle if include_message else target_cycle - 1

        # Call the SQL rollback function
        result = await conn.fetchrow(
            "SELECT * FROM rollback_to_cycle($1, $2)", self.game_id, rollback_cycle
        )

        stats = {
            "rolled_back_to_cycle": rollback_cycle,
            "deleted_facts": result["deleted_facts"],
            "deleted_events": result["deleted_events"],
            "deleted_commitments": result["deleted_commitments"],
            "reverted_attributes": result["reverted_attributes"],
            "reverted_relations": result["reverted_relations"],
            "deleted_messages": 0,
        }

        # Delete messages after the target
        if include_message:
            # Delete messages created AFTER this one
            deleted = await conn.execute(
                """DELETE FROM chat_messages 
                   WHERE game_id = $1 AND created_at > $2""",
                self.game_id,
                message_created_at,
            )
        else:
            # Delete this message and all after
            deleted = await conn.execute(
                """DELETE FROM chat_messages 
                   WHERE game_id = $1 AND created_at >= $2""",
                self.game_id,
                message_created_at,
            )

        stats["deleted_messages"] = int(deleted.split()[-1]) if deleted else 0

        # Clear registry and reload (state has changed)
        self.registry = EntityRegistry()
        await self.load_registry(conn)

        return stats

    async def rollback_to_cycle(self, conn: Connection, target_cycle: int) -> dict:
        """
        Rollback the game state to a specific cycle.
        All data after target_cycle will be deleted.

        Returns:
            Stats about what was rolled back
        """
        result = await conn.fetchrow(
            "SELECT * FROM rollback_to_cycle($1, $2)", self.game_id, target_cycle
        )

        stats = {
            "rolled_back_to_cycle": target_cycle,
            "deleted_facts": result["deleted_facts"],
            "deleted_events": result["deleted_events"],
            "deleted_commitments": result["deleted_commitments"],
            "reverted_attributes": result["reverted_attributes"],
            "reverted_relations": result["reverted_relations"],
        }

        # Delete messages after target cycle
        await conn.execute(
            "DELETE FROM chat_messages WHERE game_id = $1 AND cycle > $2",
            self.game_id,
            target_cycle,
        )

        # Clear registry and reload
        self.registry = EntityRegistry()
        await self.load_registry(conn)

        return stats

    async def get_rollback_preview(self, conn: Connection, message_id: UUID) -> dict:
        """
        Preview what would be affected by a rollback without doing it.
        Useful for showing user what they'll lose.
        """
        message = await self.get_message(conn, message_id)
        if not message:
            raise ValueError(f"Message {message_id} not found")

        target_cycle = message["cycle"]

        # Count what would be deleted
        counts = {}

        counts["messages"] = await conn.fetchval(
            "SELECT COUNT(*) FROM chat_messages WHERE game_id = $1 AND cycle > $2",
            self.game_id,
            target_cycle,
        )

        counts["facts"] = await conn.fetchval(
            "SELECT COUNT(*) FROM facts WHERE game_id = $1 AND cycle > $2",
            self.game_id,
            target_cycle,
        )

        counts["events"] = await conn.fetchval(
            "SELECT COUNT(*) FROM events WHERE game_id = $1 AND planned_cycle > $2",
            self.game_id,
            target_cycle,
        )

        counts["new_entities"] = await conn.fetchval(
            "SELECT COUNT(*) FROM entities WHERE game_id = $1 AND created_cycle > $2",
            self.game_id,
            target_cycle,
        )

        counts["modified_attributes"] = await conn.fetchval(
            "SELECT COUNT(*) FROM attributes WHERE game_id = $1 AND start_cycle > $2",
            self.game_id,
            target_cycle,
        )

        counts["new_relations"] = await conn.fetchval(
            "SELECT COUNT(*) FROM relations WHERE game_id = $1 AND start_cycle > $2",
            self.game_id,
            target_cycle,
        )

        return {
            "target_message_id": message_id,
            "target_cycle": target_cycle,
            "target_content_preview": message["content"][:200] + "..."
            if len(message["content"]) > 200
            else message["content"],
            "will_delete": counts,
        }
