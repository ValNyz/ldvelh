"""
LDVELH - Knowledge Graph Populator (EAV Architecture)
All entity data stored via attributes table
Reusable for initial generation AND narrative extraction
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from schema import (
    AttributeVisibility,
    AttributeWithVisibility,
    CharacterData,
    EntityType,
    FactData,
    get_attribute_visibility,
    LocationData,
    ObjectData,
    OrganizationData,
    PersonalAIData,
    ProtagonistData,
    RelationCategory,
    RelationData,
    RelationType,
    Skill,
    VALID_ATTRIBUTE_KEYS_BY_ENTITY,
    normalize_attribute_key,
    ATTRIBUTE_NORMALIZERS,
)

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)


# =============================================================================
# ENTITY REGISTRY
# =============================================================================


@dataclass
class EntityRegistry:
    """Tracks entity name → UUID mappings."""

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
# KNOWLEDGE GRAPH POPULATOR
# =============================================================================


class KnowledgeGraphPopulator:
    """Core populator with EAV-based entity creation."""

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
        """Load existing entities into registry"""
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
        known_by_protagonist: bool = True,
        unknown_name: str | None = None,
    ) -> UUID:
        """Create or update an entity, register it, return ID"""
        entity_id = await conn.fetchval(
            "SELECT upsert_entity($1, $2, $3, $4, $5, $6, $7)",
            self.game_id,
            entity_type.value,
            name,
            aliases or [],
            cycle,
            known_by_protagonist,
            unknown_name,
        )
        self.registry.register(name, entity_id, entity_type)

        # Insert into typed table (FK only, no data)
        await self._insert_typed_entity_row(conn, entity_type, entity_id)

        return entity_id

    async def _insert_typed_entity_row(
        self, conn: Connection, entity_type: EntityType, entity_id: UUID
    ) -> None:
        """Insert empty row in typed entity table (for FK constraints)"""
        table_map = {
            EntityType.PROTAGONIST: "entity_protagonists",
            EntityType.CHARACTER: "entity_characters",
            EntityType.LOCATION: "entity_locations",
            EntityType.OBJECT: "entity_objects",
            EntityType.AI: "entity_ais",
            EntityType.ORGANIZATION: "entity_organizations",
        }
        table = table_map.get(entity_type)
        if table:
            await conn.execute(
                f"INSERT INTO {table} (entity_id) VALUES ($1) ON CONFLICT DO NOTHING",
                entity_id,
            )

    # =========================================================================
    # ATTRIBUTES
    # =========================================================================

    async def set_attributes(
        self,
        conn: Connection,
        entity_id: UUID,
        attrs: dict[str, Any] | list[AttributeWithVisibility],
        cycle: int = 1,
        known_by_protagonist: bool | None = None,
        entity_type: EntityType | None = None,
    ) -> int:
        """
        Set multiple attributes on an entity.
        Returns number of attributes set.
        """
        # Get entity type FIRST if not provided (needed for normalization)
        if entity_type is None:
            entity_type = await self._get_entity_type(conn, entity_id)

        # Choose normalizer based on entity type
        normalizer = ATTRIBUTE_NORMALIZERS.get(entity_type, normalize_attribute_key)

        # Convert dict → list with entity-specific normalization
        if isinstance(attrs, dict):
            converted = []
            for k, v in attrs.items():
                try:
                    key = normalizer(k)  # ← Utilise le normaliseur typé
                    str_value = json.dumps(v) if isinstance(v, (list, dict)) else str(v)
                    converted.append(AttributeWithVisibility(key=key, value=str_value))
                except ValueError:
                    logger.warning(
                        f"[set_attributes] Unknown key '{k}' for {entity_type.value}"
                    )
            attrs = converted

        valid_keys = VALID_ATTRIBUTE_KEYS_BY_ENTITY.get(entity_type, set())
        count = 0

        for attr in attrs:
            # Validate key for entity type
            if attr.key not in valid_keys:
                logger.warning(
                    f"[ATTR] Skipping invalid key '{attr.key.value}' for {entity_type.value}"
                )
                continue

            # Determine visibility
            if known_by_protagonist is not None:
                known = known_by_protagonist
            elif hasattr(attr, "known_by_protagonist"):
                known = attr.known_by_protagonist
            else:
                visibility = get_attribute_visibility(attr.key)
                known = visibility != AttributeVisibility.NEVER

            # Insert
            await conn.execute(
                "SELECT set_attribute($1, $2, $3, $4, $5, $6, $7)",
                self.game_id,
                entity_id,
                attr.key.value,
                attr.value,
                cycle,
                json.dumps(attr.details) if attr.details else None,
                known,
            )
            count += 1
            logger.debug(
                f"[ATTR] {attr.key.value}={attr.value[:50]}... (known={known})"
            )

        return count

    async def _get_entity_type(self, conn: Connection, entity_id: UUID) -> EntityType:
        """Get entity type from DB"""
        row = await conn.fetchrow("SELECT type FROM entities WHERE id = $1", entity_id)
        if not row:
            raise ValueError(f"Entity not found: {entity_id}")
        return EntityType(row["type"])

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
    # TYPED ENTITY CREATION (all use attributes)
    # =========================================================================

    async def create_protagonist(
        self, conn: Connection, data: ProtagonistData, cycle: int = 1
    ) -> UUID:
        """Create the protagonist entity"""
        entity_id = await self.upsert_entity(
            conn, EntityType.PROTAGONIST, data.name, cycle=cycle
        )

        # Set all attributes
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.PROTAGONIST
        )

        # Set skills
        for skill in data.skills:
            await self.set_skill(conn, entity_id, skill, cycle)

        return entity_id

    async def create_character(
        self,
        conn: Connection,
        data: CharacterData,
        cycle: int = 1,
        known_by_protagonist: bool = True,
        unknown_name: str | None = None,
    ) -> UUID:
        """Create a character (NPC) entity"""
        entity_id = await self.upsert_entity(
            conn,
            EntityType.CHARACTER,
            data.name,
            cycle=cycle,
            known_by_protagonist=known_by_protagonist,
            unknown_name=unknown_name,
        )

        # Set all attributes
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.CHARACTER
        )

        # Auto-create spatial relations
        if data.workplace_ref:
            await self.create_relation(
                conn,
                RelationData(
                    source_ref=data.name,
                    target_ref=data.workplace_ref,
                    relation_type=RelationType.WORKS_AT,
                ),
                cycle,
            )

        if data.residence_ref:
            await self.create_relation(
                conn,
                RelationData(
                    source_ref=data.name,
                    target_ref=data.residence_ref,
                    relation_type=RelationType.LIVES_AT,
                ),
                cycle,
            )

        return entity_id

    async def create_location(
        self, conn: Connection, data: LocationData, cycle: int = 1
    ) -> UUID:
        """Create a location entity"""
        entity_id = await self.upsert_entity(
            conn, EntityType.LOCATION, data.name, cycle=cycle
        )

        # Set parent_location_id FK
        if data.parent_location_ref:
            parent_id = self.registry.resolve(data.parent_location_ref)
            if parent_id:
                await conn.execute(
                    "UPDATE entity_locations SET parent_location_id = $1 WHERE entity_id = $2",
                    parent_id,
                    entity_id,
                )

        # Set all attributes
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.LOCATION
        )

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

        # Set all attributes
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.OBJECT
        )

        # Create ownership relation if owner specified
        if owner_ref:
            owner_id = self.registry.resolve(owner_ref)
            if owner_id:
                await self.create_relation(
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

        # Set headquarters FK
        if data.headquarters_ref:
            hq_id = self.registry.resolve(data.headquarters_ref)
            if hq_id:
                await conn.execute(
                    "UPDATE entity_organizations SET headquarters_id = $1 WHERE entity_id = $2",
                    hq_id,
                    entity_id,
                )

        # Set all attributes
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.ORGANIZATION
        )

        return entity_id

    async def create_ai(
        self, conn: Connection, data: PersonalAIData, cycle: int = 1
    ) -> UUID:
        """Create a personal AI entity"""
        entity_id = await self.upsert_entity(
            conn, EntityType.AI, data.name, cycle=cycle
        )

        # Set creator FK
        if data.creator_ref:
            creator_id = self.registry.resolve(data.creator_ref)
            if creator_id:
                await conn.execute(
                    "UPDATE entity_ais SET creator_id = $1 WHERE entity_id = $2",
                    creator_id,
                    entity_id,
                )

                # Create ownership relation
                await self.create_relation(
                    conn,
                    RelationData(
                        source_ref=data.creator_ref,
                        target_ref=data.name,
                        relation_type=RelationType.OWNS,
                    ),
                    cycle,
                )

        # Set all attributes
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.AI
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
            "SELECT upsert_relation($1, $2, $3, $4, $5, $6)",
            self.game_id,
            source_id,
            target_id,
            data.relation_type.value,
            cycle,
            data.known_by_protagonist,
        )

        # Handle typed relation data
        await self._insert_typed_relation_data(conn, rel_id, data)
        return rel_id

    async def _insert_typed_relation_data(
        self, conn: Connection, rel_id: UUID, data: RelationData
    ) -> None:
        """Insert into the appropriate typed relation table"""
        rt = data.relation_type

        if rt.category == RelationCategory.SOCIAL:
            social = data.social
            if social:
                await conn.execute(
                    """INSERT INTO relations_social 
                       (relation_id, level, context, romantic_stage, family_bond)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (relation_id) DO UPDATE SET
                         level = COALESCE(EXCLUDED.level, relations_social.level),
                         context = COALESCE(EXCLUDED.context, relations_social.context)""",
                    rel_id,
                    social.level,
                    social.context,
                    social.romantic_stage,
                    social.family_bond,
                )

        elif rt.category == RelationCategory.PROFESSIONAL:
            prof = data.professional
            if prof:
                await conn.execute(
                    """INSERT INTO relations_professional 
                       (relation_id, position, position_start_cycle, part_time)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (relation_id) DO UPDATE SET
                         position = COALESCE(EXCLUDED.position, relations_professional.position)""",
                    rel_id,
                    prof.position,
                    prof.position_start_cycle,
                    prof.part_time,
                )

        elif rt.category == RelationCategory.SPATIAL:
            spatial = data.spatial
            if spatial:
                await conn.execute(
                    """INSERT INTO relations_spatial (relation_id, regularity, time_of_day)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (relation_id) DO NOTHING""",
                    rel_id,
                    spatial.regularity,
                    spatial.time_of_day,
                )

        elif rt.category == RelationCategory.OWNERSHIP:
            own = data.ownership
            await conn.execute(
                """INSERT INTO relations_ownership 
                   (relation_id, quantity, origin, amount, acquisition_cycle)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (relation_id) DO UPDATE SET
                     quantity = COALESCE(EXCLUDED.quantity, relations_ownership.quantity)""",
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
        return await conn.fetchval(
            "SELECT end_relation($1, $2, $3, $4, $5, $6)",
            self.game_id,
            source_ref,
            target_ref,
            relation_type.value,
            cycle,
            reason,
        )

    async def mark_relation_known(
        self,
        conn: Connection,
        source_ref: str,
        target_ref: str,
        relation_type: RelationType,
    ) -> bool:
        """Mark a relation as now known by protagonist"""
        source_id = self.registry.resolve(source_ref)
        target_id = self.registry.resolve(target_ref)
        if not source_id or not target_id:
            return False

        await conn.execute(
            """UPDATE relations SET known_by_protagonist = true
               WHERE game_id = $1 AND source_id = $2 AND target_id = $3 
               AND type = $4 AND end_cycle IS NULL""",
            self.game_id,
            source_id,
            target_id,
            relation_type.value,
        )
        return True

    # =========================================================================
    # FACTS
    # =========================================================================

    async def create_fact(self, conn: Connection, fact: FactData) -> UUID | None:
        """Create a fact with deduplication"""
        if fact.semantic_key:
            existing = await conn.fetchval(
                "SELECT id FROM facts WHERE game_id = $1 AND cycle = $2 AND semantic_key = $3",
                self.game_id,
                fact.cycle,
                fact.semantic_key,
            )
            if existing:
                logger.debug(f"[FACT] Duplicate ignored: {fact.semantic_key}")
                return None

        location_id = None
        if fact.location_ref:
            location_id = self.registry.resolve(fact.location_ref)

        participants_json = []
        for p in fact.participants:
            entity_id = self.registry.resolve(p.entity_ref)
            if entity_id:
                participants_json.append({"name": p.entity_ref, "role": p.role.value})

        fact_id = await conn.fetchval(
            "SELECT create_fact($1, $2, $3::fact_type, $4, $5, $6, $7, $8::jsonb, $9)",
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

        logger.info(f"[FACT] Created: [{fact.fact_type.value}] {fact.semantic_key}")
        return fact_id

    async def process_facts(self, conn: Connection, facts: list[FactData]) -> int:
        """Process a list of facts with deduplication"""
        created = 0
        seen_keys = set()

        for fact in facts:
            if fact.semantic_key in seen_keys:
                continue
            seen_keys.add(fact.semantic_key)

            fact_id = await self.create_fact(conn, fact)
            if fact_id:
                created += 1

        logger.info(f"[FACTS] {created}/{len(facts)} facts created")
        return created

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
        date: str | None = None,
        location_ref: str | None = None,
        npcs_present: list[str] | None = None,
        summary: str | None = None,
    ) -> UUID:
        """Save a chat message"""
        location_id = self.registry.resolve(location_ref) if location_ref else None
        npc_ids = []
        if npcs_present:
            for npc_ref in npcs_present:
                npc_id = self.registry.resolve(npc_ref)
                if npc_id:
                    npc_ids.append(npc_id)

        return await conn.fetchval(
            """INSERT INTO chat_messages 
               (game_id, role, content, cycle, date, location_id, npcs_present, summary)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id""",
            self.game_id,
            role,
            content,
            cycle,
            date,
            location_id,
            npc_ids,
            summary,
        )

    async def get_message(self, conn: Connection, message_id: UUID) -> dict | None:
        """Get a single message by ID"""
        row = await conn.fetchrow(
            "SELECT * FROM chat_messages WHERE id = $1 AND game_id = $2",
            message_id,
            self.game_id,
        )
        return dict(row) if row else None

    async def get_recent_messages(
        self, conn: Connection, limit: int = 20
    ) -> list[dict]:
        """Get the most recent messages"""
        rows = await conn.fetch(
            """SELECT * FROM chat_messages 
               WHERE game_id = $1 ORDER BY created_at DESC LIMIT $2""",
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
        date: str | None = None,
        key_events: dict | None = None,
        modified_relations: dict | None = None,
    ) -> UUID:
        """Save or update a cycle summary"""
        return await conn.fetchval(
            """INSERT INTO cycle_summaries 
               (game_id, cycle, date, summary, key_events, modified_relations)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (game_id, cycle) DO UPDATE SET
                 summary = EXCLUDED.summary,
                 key_events = COALESCE(EXCLUDED.key_events, cycle_summaries.key_events)
               RETURNING id""",
            self.game_id,
            cycle,
            date,
            summary,
            json.dumps(key_events) if key_events else None,
            json.dumps(modified_relations) if modified_relations else None,
        )

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_cycle(self, conn: Connection, target_cycle: int) -> dict:
        """Rollback the game state to a specific cycle"""
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

        await conn.execute(
            "DELETE FROM chat_messages WHERE game_id = $1 AND cycle > $2",
            self.game_id,
            target_cycle,
        )

        self.registry = EntityRegistry()
        await self.load_registry(conn)

        return stats
