"""
LDVELH - Knowledge Graph Populator (EAV Architecture)
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
    ENTITY_TYPED_TABLES,
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
# ENTITY REGISTRY (cache local)
# =============================================================================


@dataclass
class EntityRegistry:
    """Tracks entity name → UUID mappings (cache local)."""

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

    def clear(self) -> None:
        self._by_name.clear()
        self._by_type = {t: [] for t in EntityType}
        self._names_by_id.clear()

    def __contains__(self, name: str) -> bool:
        return name.lower().strip() in self._by_name


# =============================================================================
# KNOWLEDGE GRAPH POPULATOR
# =============================================================================


class KnowledgeGraphPopulator:
    """Populator: écriture seule (INSERT, UPDATE, DELETE)."""

    def __init__(self, pool: Pool, game_id: UUID | None = None):
        self.pool = pool
        self.game_id = game_id
        self.registry = EntityRegistry()

    # =========================================================================
    # REGISTRY (utilise reader pour charger)
    # =========================================================================

    async def load_registry(self, conn: Connection) -> None:
        """Charge les entités existantes dans le registry (via reader)"""
        if not self.game_id:
            raise ValueError("game_id must be set before loading registry")

        from kg.reader import KnowledgeGraphReader

        reader = KnowledgeGraphReader(self.pool, self.game_id)
        entities = await reader.get_entities(conn)

        self.registry.clear()
        for row in entities:
            self.registry.register(row["name"], row["id"], EntityType(row["type"]))

        logger.info(f"Loaded {len(entities)} entities into registry")

    # =========================================================================
    # GAMES - Écriture
    # =========================================================================

    async def create_game(
        self, conn: Connection, name: str = "Nouvelle partie"
    ) -> UUID:
        """Crée une nouvelle partie"""
        self.game_id = await conn.fetchval(
            "INSERT INTO games (name) VALUES ($1) RETURNING id", name
        )
        logger.info(f"Created game {self.game_id}: {name}")
        return self.game_id

    async def delete_game(self, conn: Connection, game_id: UUID | None = None) -> bool:
        """Supprime une partie (CASCADE sur toutes les tables liées)"""
        target_id = game_id or self.game_id
        result = await conn.execute("DELETE FROM games WHERE id = $1", target_id)
        return result == "DELETE 1"

    async def rename_game(
        self, conn: Connection, name: str, game_id: UUID | None = None
    ) -> None:
        """Renomme une partie"""
        target_id = game_id or self.game_id
        await conn.execute(
            "UPDATE games SET name = $1, updated_at = NOW() WHERE id = $2",
            name,
            target_id,
        )

    async def update_game_timestamp(
        self, conn: Connection, game_id: UUID | None = None
    ) -> None:
        """Met à jour le timestamp de la partie"""
        target_id = game_id or self.game_id
        await conn.execute(
            "UPDATE games SET updated_at = NOW() WHERE id = $1", target_id
        )

    async def deactivate_game(
        self, conn: Connection, game_id: UUID | None = None
    ) -> None:
        """Désactive une partie (soft delete)"""
        target_id = game_id or self.game_id
        await conn.execute(
            "UPDATE games SET active = false, updated_at = NOW() WHERE id = $1",
            target_id,
        )

    # =========================================================================
    # ENTITY CREATION - Generic
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
        """Crée ou met à jour une entité via la fonction SQL upsert_entity"""
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

        # Insert into typed table (FK only)
        await self._insert_typed_entity_row(conn, entity_type, entity_id)

        return entity_id

    async def _insert_typed_entity_row(
        self, conn: Connection, entity_type: EntityType, entity_id: UUID
    ) -> None:
        """Insert row in typed entity table (only for entities with FK constraints)"""
        table = ENTITY_TYPED_TABLES.get(entity_type)
        if table:
            await conn.execute(
                f"INSERT INTO {table} (entity_id) VALUES ($1) ON CONFLICT DO NOTHING",
                entity_id,
            )

    async def remove_entity(
        self, conn: Connection, entity_ref: str, cycle: int, reason: str
    ) -> bool:
        """Marque une entité comme supprimée"""
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
        """Set multiple attributes on an entity via la fonction SQL set_attribute"""
        # Get entity type if not provided
        if entity_type is None:
            from kg.reader import KnowledgeGraphReader

            reader = KnowledgeGraphReader(self.pool, self.game_id)
            entity = await reader.get_entity_by_id(conn, entity_id)
            if not entity:
                raise ValueError(f"Entity not found: {entity_id}")
            entity_type = EntityType(entity["type"])

        # Choose normalizer based on entity type
        normalizer = ATTRIBUTE_NORMALIZERS.get(entity_type, normalize_attribute_key)

        # Convert dict → list with entity-specific normalization
        if isinstance(attrs, dict):
            converted = []
            for k, v in attrs.items():
                try:
                    key = normalizer(k)
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

    async def set_skill(
        self, conn: Connection, entity_id: UUID, skill: Skill, cycle: int = 1
    ) -> UUID | None:
        """Set a skill on an entity via la fonction SQL set_skill"""
        return await conn.fetchval(
            "SELECT set_skill($1, $2, $3, $4, $5)",
            self.game_id,
            entity_id,
            skill.name,
            skill.level,
            cycle,
        )

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
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.PROTAGONIST
        )
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
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.CHARACTER
        )

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

        if data.parent_location_ref:
            parent_id = self.registry.resolve(data.parent_location_ref)
            if parent_id:
                await conn.execute(
                    "UPDATE entity_locations SET parent_location_id = $1 WHERE entity_id = $2",
                    parent_id,
                    entity_id,
                )

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
        await self.set_attributes(
            conn, entity_id, data.attributes, cycle, entity_type=EntityType.OBJECT
        )

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

        if data.headquarters_ref:
            hq_id = self.registry.resolve(data.headquarters_ref)
            if hq_id:
                await conn.execute(
                    "UPDATE entity_organizations SET headquarters_id = $1 WHERE entity_id = $2",
                    hq_id,
                    entity_id,
                )

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

        if data.creator_ref:
            creator_id = self.registry.resolve(data.creator_ref)
            if creator_id:
                await conn.execute(
                    "UPDATE entity_ais SET creator_id = $1 WHERE entity_id = $2",
                    creator_id,
                    entity_id,
                )
                await self.create_relation(
                    conn,
                    RelationData(
                        source_ref=data.creator_ref,
                        target_ref=data.name,
                        relation_type=RelationType.OWNS,
                    ),
                    cycle,
                )

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
        """Create or update a relation via la fonction SQL upsert_relation"""
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
        """End an existing relation via la fonction SQL end_relation"""
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
        """Create a fact via la fonction SQL create_fact (avec déduplication)"""
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

        if fact_id:
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
    # PROTAGONIST - Gauges & Credits
    # =========================================================================

    async def update_gauge(
        self, conn: Connection, gauge: str, delta: float, cycle: int
    ) -> tuple[bool, float, float]:
        """Update energy/morale/health via la fonction SQL update_gauge"""
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
        """Add or remove credits via la fonction SQL credit_transaction"""
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
        time: str | None = None,
        location_ref: str | None = None,
        npcs_present_refs: list[str] | None = None,
        summary: str | None = None,
        tone_notes: str | None = None,
    ) -> UUID:
        """Save a chat message"""
        location_id = self.registry.resolve(location_ref) if location_ref else None

        npc_ids = []
        if npcs_present_refs:
            for npc_ref in npcs_present_refs:
                npc_id = self.registry.resolve(npc_ref)
                if npc_id:
                    npc_ids.append(npc_id)

        return await conn.fetchval(
            """INSERT INTO chat_messages 
               (game_id, role, content, cycle, date, time, location_id, npcs_present, summary, tone_notes)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id""",
            self.game_id,
            role,
            content,
            cycle,
            date,
            time,
            location_id,
            npc_ids,
            summary,
            tone_notes,
        )

    async def save_message_pair(
        self,
        conn: Connection,
        user_message: str,
        assistant_message: str,
        cycle: int,
        date: str | None = None,
        time: str | None = None,
        location_ref: str | None = None,
        npcs_present_refs: list[str] | None = None,
        summary: str | None = None,
        tone_notes: str | None = None,
    ) -> tuple[UUID, UUID]:
        """Save a user + assistant message pair"""
        user_id = await self.save_message(conn, "user", user_message, cycle)
        assistant_id = await self.save_message(
            conn,
            "assistant",
            assistant_message,
            cycle,
            date,
            time,
            location_ref,
            npcs_present_refs,
            summary,
            tone_notes,
        )
        return user_id, assistant_id

    async def delete_messages_by_ids(
        self, conn: Connection, message_ids: list[UUID]
    ) -> int:
        """Supprime des messages par leurs IDs"""
        if not message_ids:
            return 0
        result = await conn.execute(
            "DELETE FROM chat_messages WHERE id = ANY($1)", message_ids
        )
        return int(result.split()[-1])

    # =========================================================================
    # CYCLE SUMMARIES
    # =========================================================================

    async def save_cycle_summary(
        self,
        conn: Connection,
        cycle: int,
        summary: str | None = None,
        date: str | None = None,
    ) -> UUID:
        """Save or update a cycle summary"""
        return await conn.fetchval(
            """INSERT INTO cycle_summaries 
               (game_id, cycle, date, summary, key_events, modified_relations)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (game_id, cycle) DO UPDATE SET
                 date = COALESCE(EXCLUDED.date, cycle_summaries.date),
                 summary = COALESCE(EXCLUDED.summary, cycle_summaries.summary),
               RETURNING id""",
            self.game_id,
            cycle,
            date,
            summary,
        )

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_cycle(self, conn: Connection, target_cycle: int) -> dict:
        """Rollback via la fonction SQL rollback_to_cycle"""
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

        # Recharger le registry
        self.registry.clear()
        await self.load_registry(conn)

        return stats

    # =========================================================================
    # ENTITY UPDATES
    # =========================================================================

    async def update_entity_aliases(
        self, conn: Connection, entity_id: UUID, new_aliases: list[str]
    ) -> None:
        """Ajoute des aliases à une entité"""
        await conn.execute(
            """UPDATE entities SET 
               aliases = ARRAY(SELECT DISTINCT unnest(aliases || $1)),
               updated_at = NOW()
               WHERE id = $2""",
            new_aliases,
            entity_id,
        )

    async def mark_entity_known(
        self, conn: Connection, entity_id: UUID, real_name: str | None = None
    ) -> None:
        """Marque une entité comme connue par le protagoniste"""
        if real_name:
            await conn.execute(
                """UPDATE entities 
                   SET known_by_protagonist = true, name = $1, updated_at = NOW() 
                   WHERE id = $2""",
                real_name,
                entity_id,
            )
        else:
            await conn.execute(
                "UPDATE entities SET known_by_protagonist = true, updated_at = NOW() WHERE id = $1",
                entity_id,
            )

    async def update_entity_fk(
        self,
        conn: Connection,
        entity_type: EntityType,
        entity_id: UUID,
        fk_field: str,
        fk_value: UUID | None,
    ) -> None:
        """Met à jour une FK sur une table typée"""
        table = ENTITY_TYPED_TABLES.get(entity_type)
        if not table:
            return

        # Whitelist des champs FK autorisés par table
        valid_fks = {
            "entity_locations": ["parent_location_id"],
            "entity_ais": ["creator_id"],
            "entity_organizations": ["headquarters_id"],
        }

        if fk_field not in valid_fks.get(table, []):
            logger.warning(f"Invalid FK field {fk_field} for table {table}")
            return

        await conn.execute(
            f"UPDATE {table} SET {fk_field} = $1 WHERE entity_id = $2",
            fk_value,
            entity_id,
        )

    # =========================================================================
    # COMMITMENTS
    # =========================================================================

    async def create_commitment(
        self,
        conn: Connection,
        commitment_type: str,
        description: str,
        cycle: int,
        deadline_cycle: int | None = None,
    ) -> UUID:
        """Crée un engagement narratif"""
        return await conn.fetchval(
            """INSERT INTO commitments 
               (game_id, type, description, created_cycle, deadline_cycle)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            self.game_id,
            commitment_type,
            description,
            cycle,
            deadline_cycle,
        )

    async def create_commitment_arc(
        self,
        conn: Connection,
        commitment_id: UUID,
        objective: str,
        obstacle: str,
    ) -> None:
        """Ajoute les détails d'arc à un commitment"""
        await conn.execute(
            """INSERT INTO commitment_arcs (commitment_id, objective, obstacle)
               VALUES ($1, $2, $3)""",
            commitment_id,
            objective,
            obstacle,
        )

    async def add_commitment_entity(
        self,
        conn: Connection,
        commitment_id: UUID,
        entity_id: UUID,
        role: str | None = None,
    ) -> None:
        """Lie une entité à un commitment"""
        await conn.execute(
            """INSERT INTO commitment_entities (commitment_id, entity_id, role)
               VALUES ($1, $2, $3) ON CONFLICT DO NOTHING""",
            commitment_id,
            entity_id,
            role,
        )

    async def resolve_commitment(
        self,
        conn: Connection,
        commitment_id: UUID,
        resolution_fact_id: UUID | None = None,
    ) -> None:
        """Marque un commitment comme résolu"""
        await conn.execute(
            "UPDATE commitments SET resolved = true, resolution_fact_id = $1 WHERE id = $2",
            resolution_fact_id,
            commitment_id,
        )

    # =========================================================================
    # EVENTS
    # =========================================================================

    async def create_event(
        self,
        conn: Connection,
        event_type: str,
        title: str,
        planned_cycle: int,
        description: str | None = None,
        time: str | None = None,
        location_ref: str | None = None,
        recurrence: dict | None = None,
        amount: int | None = None,
        completed: bool = False,
        source_fact_id: UUID | None = None,
    ) -> UUID:
        """Crée un événement planifié"""
        location_id = self.registry.resolve(location_ref) if location_ref else None

        return await conn.fetchval(
            """INSERT INTO events 
               (game_id, type, title, description, planned_cycle, time, 
                location_id, recurrence, amount, completed, source_fact_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING id""",
            self.game_id,
            event_type,
            title,
            description,
            planned_cycle,
            time,
            location_id,
            json.dumps(recurrence) if recurrence else None,
            amount,
            completed,
            source_fact_id,
        )

    async def add_event_participant(
        self,
        conn: Connection,
        event_id: UUID,
        entity_id: UUID,
        role: str | None = None,
        confirmed: bool = False,
    ) -> None:
        """Ajoute un participant à un événement"""
        await conn.execute(
            """INSERT INTO event_participants (event_id, entity_id, role, confirmed)
               VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING""",
            event_id,
            entity_id,
            role,
            confirmed,
        )

    async def add_event_to_cycle_summary(
        self,
        conn: Connection,
        cycle_summary_id: UUID,
        event_id: UUID,
        role: str = "primary",
        display_order: int = 0,
    ) -> None:
        """Add an event to a cycle summary"""
        await conn.execute(
            """INSERT INTO cycle_summary_events 
               (cycle_summary_id, event_id, role, display_order)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (cycle_summary_id, event_id) DO UPDATE SET
                 role = EXCLUDED.role,
                 display_order = EXCLUDED.display_order""",
            cycle_summary_id,
            event_id,
            role,
            display_order,
        )

    # =========================================================================
    # EXTRACTION LOGS
    # =========================================================================

    async def log_extraction(
        self,
        conn: Connection,
        cycle: int,
        stats: dict,
    ) -> UUID:
        """Enregistre les stats d'une extraction"""
        return await conn.fetchval(
            """INSERT INTO extraction_logs 
               (game_id, cycle, entities_created, relations_created,
                facts_created, attributes_modified, errors)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
            self.game_id,
            cycle,
            stats.get("entities_created", 0) + stats.get("objects_created", 0),
            stats.get("relations_created", 0),
            stats.get("facts_created", 0),
            stats.get("entities_updated", 0),
            json.dumps(stats.get("errors")) if stats.get("errors") else None,
        )
