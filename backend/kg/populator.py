"""
LDVELH - Knowledge Graph Populator (Dedicated Tables Architecture)
Write operations for all game data tables.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from schema import (
    CharacterData,
    EntityType,
    FactData,
    LocationData,
    NarrativeArcData,
    ObjectData,
    OrganizationData,
    PersonalAssistantData,
    ProtagonistData,
    RelationData,
    RelationType,
    Skill,
)

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)


# =============================================================================
# ENTITY REGISTRY (local cache for entity_registry UUIDs)
# =============================================================================


@dataclass
class EntityRegistry:
    """Tracks entity name → entity_registry UUID mappings (local cache)."""

    _by_name: dict[str, UUID] = field(default_factory=dict)
    _by_type: dict[str, list[UUID]] = field(default_factory=dict)
    _names_by_id: dict[UUID, str] = field(default_factory=dict)

    def register(
        self, name: str, entity_id: UUID, entity_type: str | EntityType
    ) -> None:
        key = name.lower().strip()
        type_key = (
            entity_type.value if isinstance(entity_type, EntityType) else entity_type
        )
        self._by_name[key] = entity_id
        self._by_type.setdefault(type_key, []).append(entity_id)
        self._names_by_id[entity_id] = name

    def resolve(self, name: str) -> UUID | None:
        return self._by_name.get(name.lower().strip())

    def resolve_strict(self, name: str) -> UUID:
        result = self.resolve(name)
        if result is None:
            raise KeyError(f"Entity not found: '{name}'")
        return result

    def get_by_type(self, entity_type: str | EntityType) -> list[UUID]:
        key = (
            entity_type.value if isinstance(entity_type, EntityType) else entity_type
        )
        return self._by_type.get(key, []).copy()

    def get_name(self, entity_id: UUID) -> str | None:
        return self._names_by_id.get(entity_id)

    def clear(self) -> None:
        self._by_name.clear()
        self._by_type.clear()
        self._names_by_id.clear()

    def __contains__(self, name: str) -> bool:
        return name.lower().strip() in self._by_name


# =============================================================================
# KNOWLEDGE GRAPH POPULATOR
# =============================================================================


class KnowledgeGraphPopulator:
    """Write operations for the dedicated tables architecture."""

    def __init__(self, pool: Pool, game_id: UUID | None = None):
        self.pool = pool
        self.game_id = game_id
        self.registry = EntityRegistry()

    # =========================================================================
    # REGISTRY
    # =========================================================================

    async def load_registry(self, conn: Connection) -> None:
        """Load all entity_registry entries into local cache."""
        if not self.game_id:
            raise ValueError("game_id must be set before loading registry")

        rows = await conn.fetch(
            "SELECT id, entity_type, name FROM entity_registry WHERE game_id = $1",
            self.game_id,
        )
        self.registry.clear()
        for row in rows:
            self.registry.register(row["name"], row["id"], row["entity_type"])
        logger.info(f"Loaded {len(rows)} entities into registry")

    # =========================================================================
    # GAMES
    # =========================================================================

    async def create_game(
        self,
        conn: Connection,
        name: str = "Nouvelle partie",
        user_id: UUID | None = None,
    ) -> UUID:
        """Create a new game. user_id required by DB (NOT NULL)."""
        self.game_id = await conn.fetchval(
            "INSERT INTO games (user_id, name) VALUES ($1, $2) RETURNING id",
            user_id,
            name,
        )
        logger.info(f"Created game {self.game_id}: {name}")
        return self.game_id

    async def delete_game(
        self, conn: Connection, game_id: UUID | None = None
    ) -> bool:
        target_id = game_id or self.game_id
        result = await conn.execute("DELETE FROM games WHERE id = $1", target_id)
        return result == "DELETE 1"

    async def rename_game(
        self, conn: Connection, name: str, game_id: UUID | None = None
    ) -> None:
        target_id = game_id or self.game_id
        await conn.execute(
            "UPDATE games SET name = $1, updated_at = NOW() WHERE id = $2",
            name,
            target_id,
        )

    async def update_game_state(
        self,
        conn: Connection,
        *,
        cycle: int | None = None,
        date: str | None = None,
        time: str | None = None,
        location_id: UUID | None = None,
    ) -> None:
        """Update current game state (cycle, date, time, location)."""
        sets = ["updated_at = NOW()"]
        params: list = [self.game_id]
        if cycle is not None:
            params.append(cycle)
            sets.append(f"current_cycle = ${len(params)}")
        if date is not None:
            params.append(date)
            sets.append(f'"current_date" = ${len(params)}')
        if time is not None:
            params.append(time)
            sets.append(f'"current_time" = ${len(params)}')
        if location_id is not None:
            params.append(location_id)
            sets.append(f"current_location_id = ${len(params)}")

        if len(params) == 1:
            return
        await conn.execute(
            f"UPDATE games SET {', '.join(sets)} WHERE id = $1", *params
        )

    async def update_extracted_cycle(
        self, conn: Connection, cycle: int
    ) -> None:
        """Update extracted_up_to_cycle tracking column."""
        await conn.execute(
            "UPDATE games SET extracted_up_to_cycle = $1, updated_at = NOW()"
            " WHERE id = $2",
            cycle, self.game_id,
        )

    async def update_detail_requests(
        self, conn: Connection, requests: list[str]
    ) -> None:
        """Store entity detail requests for next turn."""
        await conn.execute(
            "UPDATE games SET detail_requests = $1 WHERE id = $2",
            requests, self.game_id,
        )

    async def clear_detail_requests(self, conn: Connection) -> None:
        """Clear entity detail requests (on cycle change)."""
        await conn.execute(
            "UPDATE games SET detail_requests = '{}' WHERE id = $1",
            self.game_id,
        )

    async def create_stub_event(
        self, conn: Connection, event_hint, cycle: int
    ) -> None:
        """Create a stub event from narrator EventHint (formalized at extraction time)."""
        # Resolve location_id if location name provided
        location_id = None
        if event_hint.location:
            location_id = await conn.fetchval(
                "SELECT id FROM locations WHERE game_id=$1 AND LOWER(name)=LOWER($2)",
                self.game_id, event_hint.location,
            )
        # Avoid duplicates by title + planned_cycle
        planned_cycle = event_hint.planned_cycle or cycle + 1
        existing = await conn.fetchval(
            "SELECT id FROM events WHERE game_id=$1 AND title=$2 AND planned_cycle=$3",
            self.game_id, event_hint.title, planned_cycle,
        )
        if not existing:
            await conn.execute(
                """INSERT INTO events (game_id, title, type, planned_cycle, time, location_id)
                VALUES ($1, $2, 'appointment', $3, $4, $5)""",
                self.game_id, event_hint.title, planned_cycle,
                event_hint.planned_time, location_id,
            )
            logger.info(
                f"[KG] Created stub event '{event_hint.title}' "
                f"(cycle {planned_cycle})"
            )

    async def update_game_timestamp(
        self, conn: Connection, game_id: UUID | None = None
    ) -> None:
        target_id = game_id or self.game_id
        await conn.execute(
            "UPDATE games SET updated_at = NOW() WHERE id = $1", target_id
        )

    async def deactivate_game(
        self, conn: Connection, game_id: UUID | None = None
    ) -> None:
        target_id = game_id or self.game_id
        await conn.execute(
            "UPDATE games SET active = false, updated_at = NOW() WHERE id = $1",
            target_id,
        )

    # =========================================================================
    # WORLD (stored on games table)
    # =========================================================================

    async def set_world_data(
        self,
        conn: Connection,
        world,
        seed_words: list[str] | None = None,
    ) -> None:
        """Store world metadata on the games table."""
        await conn.execute(
            """UPDATE games SET
                world_name = $2, world_description = $3, world_atmosphere = $4,
                world_seed_words = $5, world_founding_cycle = $6, updated_at = NOW()
            WHERE id = $1""",
            self.game_id,
            world.name,
            world.description,
            world.atmosphere,
            seed_words or getattr(world, "seed_words", []) or [],
            world.founding_cycle,
        )

    # =========================================================================
    # FK RESOLUTION HELPERS
    # =========================================================================

    async def _resolve_location_id(
        self, conn: Connection, name: str | None
    ) -> UUID | None:
        if not name:
            return None
        return await conn.fetchval(
            "SELECT id FROM locations WHERE game_id = $1 AND LOWER(name) = LOWER($2)"
            " AND removed_cycle IS NULL",
            self.game_id,
            name.strip(),
        )

    async def _resolve_organization_id(
        self, conn: Connection, name: str | None
    ) -> UUID | None:
        if not name:
            return None
        return await conn.fetchval(
            "SELECT id FROM organizations WHERE game_id = $1 AND LOWER(name) = LOWER($2)"
            " AND removed_cycle IS NULL",
            self.game_id,
            name.strip(),
        )

    async def _resolve_object_id(
        self, conn: Connection, name: str | None
    ) -> UUID | None:
        if not name:
            return None
        return await conn.fetchval(
            "SELECT id FROM objects WHERE game_id = $1 AND LOWER(name) = LOWER($2)"
            " AND removed_cycle IS NULL",
            self.game_id,
            name.strip(),
        )

    async def _resolve_protagonist_id(self, conn: Connection) -> UUID | None:
        return await conn.fetchval(
            "SELECT id FROM protagonists WHERE game_id = $1", self.game_id
        )

    # =========================================================================
    # ENTITY CREATION — direct table inserts
    # Triggers auto-populate entity_registry.
    # =========================================================================

    async def create_protagonist(
        self, conn: Connection, data: ProtagonistData
    ) -> UUID:
        """Insert protagonist into dedicated table."""
        reason = (
            data.departure_reason.value
            if hasattr(data.departure_reason, "value")
            else str(data.departure_reason)
        )
        row_id = await conn.fetchval(
            """INSERT INTO protagonists (
                game_id, name, energy, morale, health, credits,
                occupation, origin, departure_reason, backstory,
                hobbies, description, details
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            RETURNING id""",
            self.game_id,
            data.name,
            data.energy,
            data.morale,
            data.health,
            data.credits,
            data.occupation,
            data.origin,
            reason,
            data.backstory,
            data.hobbies,
            data.description,
            json.dumps(data.details) if data.details else "{}",
        )
        for skill in data.skills:
            await self._insert_skill(conn, skill, protagonist_id=row_id)
        return row_id

    async def create_personal_assistant(
        self, conn: Connection, data: PersonalAssistantData
    ) -> UUID:
        """Insert personal assistant into dedicated table."""
        return await conn.fetchval(
            """INSERT INTO personal_assistants (
                game_id, name, voice, traits, quirk, substrate, details
            ) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
            self.game_id,
            data.name,
            data.voice,
            data.traits,
            data.quirk,
            data.substrate or "terminal personnel",
            json.dumps(data.details) if data.details else "{}",
        )

    async def create_character(
        self,
        conn: Connection,
        data: CharacterData,
        cycle: int = 1,
        workplace_id: UUID | None = None,
        residence_id: UUID | None = None,
    ) -> UUID:
        """Insert character (NPC) into dedicated table."""
        return await conn.fetchval(
            """INSERT INTO characters (
                game_id, name, known_by_protagonist, unknown_name,
                species, gender, pronouns, age, description,
                traits, mood, occupation, origin,
                workplace_id, residence_id,
                romantic_potential, is_mandatory, ambient,
                details, created_cycle
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
            ON CONFLICT (game_id, name) DO UPDATE SET
                known_by_protagonist = EXCLUDED.known_by_protagonist,
                species = COALESCE(EXCLUDED.species, characters.species),
                description = COALESCE(EXCLUDED.description, characters.description),
                traits = EXCLUDED.traits,
                mood = COALESCE(EXCLUDED.mood, characters.mood),
                occupation = COALESCE(EXCLUDED.occupation, characters.occupation),
                workplace_id = COALESCE(EXCLUDED.workplace_id, characters.workplace_id),
                residence_id = COALESCE(EXCLUDED.residence_id, characters.residence_id),
                updated_at = NOW()
            RETURNING id""",
            self.game_id,
            data.name,
            data.known_by_protagonist,
            data.unknown_name,
            data.species,
            data.gender,
            data.pronouns,
            data.age,
            data.description,
            data.traits,
            data.mood,
            data.occupation,
            data.origin,
            workplace_id,
            residence_id,
            data.romantic_potential,
            data.is_mandatory,
            data.ambient,
            json.dumps(data.details) if data.details else "{}",
            cycle,
        )

    async def create_location(
        self,
        conn: Connection,
        data: LocationData,
        cycle: int = 1,
        parent_id: UUID | None = None,
    ) -> UUID:
        """Insert location into dedicated table."""
        return await conn.fetchval(
            """INSERT INTO locations (
                game_id, name, parent_id,
                location_type, sector, description, atmosphere, accessible,
                notable_features, typical_crowd, operating_hours, price_range,
                ambient, details, created_cycle
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            ON CONFLICT (game_id, name) DO UPDATE SET
                parent_id = COALESCE(EXCLUDED.parent_id, locations.parent_id),
                location_type = COALESCE(EXCLUDED.location_type, locations.location_type),
                sector = COALESCE(EXCLUDED.sector, locations.sector),
                description = COALESCE(EXCLUDED.description, locations.description),
                atmosphere = COALESCE(EXCLUDED.atmosphere, locations.atmosphere),
                updated_at = NOW()
            RETURNING id""",
            self.game_id,
            data.name,
            parent_id,
            data.location_type,
            data.sector,
            data.description,
            data.atmosphere,
            data.accessible,
            data.notable_features,
            data.typical_crowd,
            data.operating_hours,
            data.price_range,
            data.ambient,
            json.dumps(data.details) if data.details else "{}",
            cycle,
        )

    async def create_organization(
        self,
        conn: Connection,
        data: OrganizationData,
        cycle: int = 1,
        headquarters_id: UUID | None = None,
    ) -> UUID:
        """Insert organization into dedicated table."""
        return await conn.fetchval(
            """INSERT INTO organizations (
                game_id, name, org_type, domain, size, description,
                reputation, headquarters_id, founding_cycle,
                ambient, details, created_cycle
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT (game_id, name) DO UPDATE SET
                org_type = COALESCE(EXCLUDED.org_type, organizations.org_type),
                domain = COALESCE(EXCLUDED.domain, organizations.domain),
                description = COALESCE(EXCLUDED.description, organizations.description),
                headquarters_id = COALESCE(EXCLUDED.headquarters_id, organizations.headquarters_id),
                updated_at = NOW()
            RETURNING id""",
            self.game_id,
            data.name,
            data.org_type,
            data.domain,
            data.size,
            data.description,
            data.reputation,
            headquarters_id,
            data.founding_cycle,
            data.ambient,
            json.dumps(data.details) if data.details else "{}",
            cycle,
        )

    async def create_object(
        self, conn: Connection, data: ObjectData, cycle: int = 1
    ) -> UUID:
        """Insert object into dedicated table. Returns existing ID on conflict."""
        obj_id = await conn.fetchval(
            """INSERT INTO objects (
                game_id, name, category, description,
                transportable, stackable, base_value, details, created_cycle
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (game_id, name) DO NOTHING
            RETURNING id""",
            self.game_id,
            data.name,
            data.category,
            data.description,
            data.transportable,
            data.stackable,
            data.base_value,
            json.dumps(data.details) if data.details else "{}",
            cycle,
        )
        if not obj_id:
            obj_id = await self._resolve_object_id(conn, data.name)
        return obj_id

    # =========================================================================
    # ENTITY UPDATES
    # =========================================================================

    async def update_entity(
        self, conn: Connection, entity_type: EntityType, name: str, changes: dict
    ) -> bool:
        """Update fields on an entity by type and name."""
        table_map = {
            EntityType.CHARACTER: ("characters", {
                "known_by_protagonist", "unknown_name", "species", "gender",
                "pronouns", "age", "description", "traits", "mood",
                "occupation", "origin", "workplace_id", "residence_id",
                "romantic_potential", "is_mandatory", "ambient",
            }),
            EntityType.LOCATION: ("locations", {
                "location_type", "sector", "description", "atmosphere",
                "accessible", "notable_features", "typical_crowd",
                "operating_hours", "price_range", "ambient",
            }),
            EntityType.ORGANIZATION: ("organizations", {
                "org_type", "domain", "size", "description", "reputation",
                "headquarters_id", "founding_cycle", "ambient",
            }),
        }

        entry = table_map.get(entity_type)
        if not entry:
            logger.warning(f"Cannot update entity type: {entity_type}")
            return False

        table, valid_fields = entry
        filtered = {k: v for k, v in changes.items() if k in valid_fields}
        if not filtered:
            return False

        sets = [f"{k} = ${i + 3}" for i, k in enumerate(filtered)]
        sets.append("updated_at = NOW()")

        result = await conn.execute(
            f"UPDATE {table} SET {', '.join(sets)}"
            f" WHERE game_id = $1 AND LOWER(name) = LOWER($2)",
            self.game_id,
            name,
            *filtered.values(),
        )
        return result != "UPDATE 0"

    async def remove_entity(
        self,
        conn: Connection,
        entity_ref: str,
        entity_type: EntityType,
        cycle: int,
    ) -> bool:
        """Mark entity as removed (set removed_cycle)."""
        table = {
            EntityType.CHARACTER: "characters",
            EntityType.LOCATION: "locations",
            EntityType.ORGANIZATION: "organizations",
            EntityType.OBJECT: "objects",
        }.get(entity_type)
        if not table:
            return False

        result = await conn.execute(
            f"UPDATE {table} SET removed_cycle = $1, updated_at = NOW()"
            f" WHERE game_id = $2 AND LOWER(name) = LOWER($3)"
            f" AND removed_cycle IS NULL",
            cycle,
            self.game_id,
            entity_ref,
        )
        return result != "UPDATE 0"

    async def mark_character_known(
        self, conn: Connection, name: str, real_name: str | None = None
    ) -> bool:
        """Reveal a character's identity to the protagonist."""
        if real_name:
            result = await conn.execute(
                "UPDATE characters SET known_by_protagonist = true,"
                " name = $1, updated_at = NOW()"
                " WHERE game_id = $2 AND LOWER(name) = LOWER($3)",
                real_name,
                self.game_id,
                name,
            )
        else:
            result = await conn.execute(
                "UPDATE characters SET known_by_protagonist = true,"
                " updated_at = NOW()"
                " WHERE game_id = $1 AND LOWER(name) = LOWER($2)",
                self.game_id,
                name,
            )
        return result != "UPDATE 0"

    async def mark_location_accessible(
        self, conn: Connection, name: str
    ) -> bool:
        """Mark a location as accessible."""
        result = await conn.execute(
            "UPDATE locations SET accessible = true, updated_at = NOW()"
            " WHERE game_id = $1 AND LOWER(name) = LOWER($2)",
            self.game_id,
            name,
        )
        return result != "UPDATE 0"

    # =========================================================================
    # RELATIONS
    # =========================================================================

    async def create_relation(
        self, conn: Connection, data: RelationData, cycle: int = 1
    ) -> UUID | None:
        """Create or update a relation via SQL function upsert_relation."""
        source_id = self.registry.resolve(data.source_ref)
        target_id = self.registry.resolve(data.target_ref)
        if not source_id or not target_id:
            logger.warning(
                f"Cannot create relation: {data.source_ref} -> {data.target_ref}"
                " (missing entity)"
            )
            return None

        return await conn.fetchval(
            "SELECT upsert_relation($1, $2, $3, $4::relation_type, $5, $6, $7, $8)",
            self.game_id,
            source_id,
            target_id,
            data.relation_type.value,
            cycle,
            data.level,
            data.context,
            data.known_by_protagonist,
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
        """End a relation via SQL function end_relation."""
        return await conn.fetchval(
            "SELECT end_relation($1, $2, $3, $4::relation_type, $5, $6)",
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
        """Mark a relation as known by protagonist."""
        source_id = self.registry.resolve(source_ref)
        target_id = self.registry.resolve(target_ref)
        if not source_id or not target_id:
            return False

        await conn.execute(
            """UPDATE relations SET known_by_protagonist = true
               WHERE game_id = $1 AND source_id = $2 AND target_id = $3
               AND type = $4::relation_type AND end_cycle IS NULL""",
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
        """Create a fact via SQL function create_fact (with deduplication)."""
        location_id = await self._resolve_location_id(conn, fact.location_ref)

        participants_json = []
        for p in fact.participants:
            entity_id = self.registry.resolve(p.entity_ref)
            if entity_id:
                participants_json.append(
                    {"name": p.entity_ref, "role": p.role.value}
                )

        fact_id = await conn.fetchval(
            "SELECT create_fact($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)",
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
            logger.info(
                f"[FACT] Created: [{fact.fact_type.value}] {fact.semantic_key}"
            )
        return fact_id

    async def process_facts(self, conn: Connection, facts: list[FactData]) -> int:
        """Process a list of facts with deduplication."""
        created = 0
        seen_keys: set[str] = set()
        for fact in facts:
            if fact.semantic_key in seen_keys:
                continue
            seen_keys.add(fact.semantic_key)
            if await self.create_fact(conn, fact):
                created += 1
        logger.info(f"[FACTS] {created}/{len(facts)} facts created")
        return created

    # =========================================================================
    # PROTAGONIST — Gauges & Credits
    # =========================================================================

    async def update_gauge(
        self, conn: Connection, gauge: str, delta: float, cycle: int
    ) -> tuple[bool, float, float]:
        """Update energy/morale/health via SQL function update_gauge."""
        result = await conn.fetchrow(
            "SELECT * FROM update_gauge($1, $2, $3, $4)",
            self.game_id,
            gauge,
            delta,
            cycle,
        )
        return result["success"], result["old_value"], result["new_value"]

    async def credit_transaction(
        self,
        conn: Connection,
        amount: int,
        cycle: int,
        description: str | None = None,
    ) -> tuple[bool, int, str | None]:
        """Add or remove credits via SQL function credit_transaction."""
        result = await conn.fetchrow(
            "SELECT * FROM credit_transaction($1, $2, $3, $4)",
            self.game_id,
            amount,
            cycle,
            description,
        )
        return result["success"], result["new_balance"], result["error"]

    # =========================================================================
    # SKILLS
    # =========================================================================

    async def _insert_skill(
        self,
        conn: Connection,
        skill: Skill,
        cycle: int = 1,
        protagonist_id: UUID | None = None,
        character_id: UUID | None = None,
    ) -> UUID:
        return await conn.fetchval(
            """INSERT INTO skills (game_id, protagonist_id, character_id,
                                   name, level, start_cycle)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
            self.game_id,
            protagonist_id,
            character_id,
            skill.name,
            skill.level,
            cycle,
        )

    async def update_skill(
        self,
        conn: Connection,
        skill: Skill,
        cycle: int,
        protagonist_id: UUID | None = None,
        character_id: UUID | None = None,
    ) -> None:
        """End current skill version and create updated one."""
        owner_col = "protagonist_id" if protagonist_id else "character_id"
        owner_id = protagonist_id or character_id
        await conn.execute(
            f"UPDATE skills SET end_cycle = $1"
            f" WHERE game_id = $2 AND {owner_col} = $3"
            f" AND LOWER(name) = LOWER($4) AND end_cycle IS NULL",
            cycle,
            self.game_id,
            owner_id,
            skill.name,
        )
        await self._insert_skill(conn, skill, cycle, protagonist_id, character_id)

    # =========================================================================
    # INVENTORY
    # =========================================================================

    async def add_to_inventory(
        self,
        conn: Connection,
        object_id: UUID,
        quantity: int = 1,
        owner_id: UUID | None = None,
        cycle: int | None = None,
        origin: str | None = None,
    ) -> UUID:
        """Add object to inventory (upsert: increment quantity if exists)."""
        existing = await conn.fetchval(
            "SELECT id FROM inventory"
            " WHERE game_id = $1 AND object_id = $2"
            " AND owner_id IS NOT DISTINCT FROM $3",
            self.game_id,
            object_id,
            owner_id,
        )
        if existing:
            await conn.execute(
                "UPDATE inventory SET quantity = quantity + $2 WHERE id = $1",
                existing,
                quantity,
            )
            return existing

        return await conn.fetchval(
            """INSERT INTO inventory
               (game_id, object_id, owner_id, quantity, acquired_cycle, origin)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
            self.game_id,
            object_id,
            owner_id,
            quantity,
            cycle,
            origin,
        )

    async def remove_from_inventory(
        self,
        conn: Connection,
        object_id: UUID,
        quantity: int = 1,
        owner_id: UUID | None = None,
    ) -> bool:
        """Remove object from inventory (reduce quantity or delete row)."""
        current = await conn.fetchval(
            "SELECT quantity FROM inventory"
            " WHERE game_id = $1 AND object_id = $2"
            " AND owner_id IS NOT DISTINCT FROM $3",
            self.game_id,
            object_id,
            owner_id,
        )
        if not current:
            return False

        if current <= quantity:
            await conn.execute(
                "DELETE FROM inventory"
                " WHERE game_id = $1 AND object_id = $2"
                " AND owner_id IS NOT DISTINCT FROM $3",
                self.game_id,
                object_id,
                owner_id,
            )
        else:
            await conn.execute(
                "UPDATE inventory SET quantity = quantity - $4"
                " WHERE game_id = $1 AND object_id = $2"
                " AND owner_id IS NOT DISTINCT FROM $3",
                self.game_id,
                object_id,
                owner_id,
                quantity,
            )
        return True

    # =========================================================================
    # NARRATIVE ARCS
    # =========================================================================

    async def create_narrative_arc(
        self, conn: Connection, arc: NarrativeArcData
    ) -> UUID:
        """Create a narrative arc with participants (dedup by title)."""
        domain = (
            arc.domain.value if hasattr(arc.domain, "value") else str(arc.domain)
        )

        # Dedup: check for existing arc with same title
        existing_id = await conn.fetchval(
            "SELECT id FROM narrative_arcs"
            " WHERE game_id = $1 AND LOWER(title) = LOWER($2)"
            " AND resolved = false",
            self.game_id,
            arc.title,
        )
        if existing_id:
            logger.info(f"[ARC] Arc already exists: '{arc.title}', updating instead")
            await conn.execute(
                """UPDATE narrative_arcs SET
                    description = COALESCE(NULLIF($3, ''), description),
                    intensity = $4, updated_at = NOW()
                WHERE id = $2 AND game_id = $1""",
                self.game_id,
                existing_id,
                arc.description,
                arc.intensity,
            )
            arc_id = existing_id
        else:
            arc_id = await conn.fetchval(
                """INSERT INTO narrative_arcs (
                    game_id, title, domain, description,
                    intensity, progress, situation, desire, obstacle,
                    potential_triggers, stakes, deadline_cycle
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING id""",
                self.game_id,
                arc.title,
                domain,
                arc.description,
                arc.intensity,
                arc.progress,
                arc.situation,
                arc.desire,
                arc.obstacle,
                arc.potential_triggers,
                arc.stakes,
                arc.deadline_cycle,
            )

        for entity_name in arc.involved_entities:
            entity_id = self.registry.resolve(entity_name)
            if entity_id:
                await conn.execute(
                    "INSERT INTO arc_participants (arc_id, entity_id, role)"
                    " VALUES ($1, $2, 'involved') ON CONFLICT DO NOTHING",
                    arc_id,
                    entity_id,
                )
            else:
                logger.warning(
                    f"[ARC] Entity not found for arc '{arc.title}': '{entity_name}'"
                )
        return arc_id

    async def update_arc(
        self,
        conn: Connection,
        arc_title: str,
        intensity: int | None = None,
        progress: int | None = None,
        situation: str | None = None,
    ) -> bool:
        """Update progress/intensity/situation on an existing arc."""
        sets = ["updated_at = NOW()"]
        params: list = [self.game_id, arc_title]
        if intensity is not None:
            params.append(intensity)
            sets.append(f"intensity = ${len(params)}")
        if progress is not None:
            params.append(progress)
            sets.append(f"progress = ${len(params)}")
        if situation is not None:
            params.append(situation)
            sets.append(f"situation = ${len(params)}")

        if len(params) == 2:
            return False

        result = await conn.execute(
            f"""UPDATE narrative_arcs SET {', '.join(sets)}
            WHERE game_id = $1 AND LOWER(title) = LOWER($2)
              AND resolved = false""",
            *params,
        )
        return result != "UPDATE 0"

    async def resolve_arc(
        self, conn: Connection, arc_title: str, resolution: str, cycle: int
    ) -> bool:
        """Resolve a narrative arc by title."""
        result = await conn.execute(
            """UPDATE narrative_arcs SET
                resolved = true, resolved_cycle = $3,
                resolution = $4, updated_at = NOW()
            WHERE game_id = $1 AND LOWER(title) = LOWER($2)
              AND resolved = false""",
            self.game_id,
            arc_title,
            cycle,
            resolution,
        )
        return result != "UPDATE 0"

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
        completed: bool = False,
    ) -> UUID:
        """Create a scheduled event."""
        location_id = await self._resolve_location_id(conn, location_ref)
        return await conn.fetchval(
            """INSERT INTO events
               (game_id, type, title, description,
                planned_cycle, time, location_id, completed)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
            self.game_id,
            event_type,
            title,
            description,
            planned_cycle,
            time,
            location_id,
            completed,
        )

    async def add_event_participant(
        self, conn: Connection, event_id: UUID, entity_id: UUID
    ) -> None:
        await conn.execute(
            "INSERT INTO event_participants (event_id, entity_id)"
            " VALUES ($1, $2) ON CONFLICT DO NOTHING",
            event_id,
            entity_id,
        )

    # =========================================================================
    # CONVERSATIONS & MESSAGES
    # =========================================================================

    async def create_conversation(
        self, conn: Connection, start_cycle: int
    ) -> UUID:
        return await conn.fetchval(
            "INSERT INTO conversations (game_id, start_cycle)"
            " VALUES ($1, $2) RETURNING id",
            self.game_id,
            start_cycle,
        )

    async def get_active_conversation(self, conn: Connection) -> UUID | None:
        return await conn.fetchval(
            "SELECT id FROM conversations"
            " WHERE game_id = $1 AND compacted = false"
            " ORDER BY created_at DESC LIMIT 1",
            self.game_id,
        )

    async def save_message(
        self,
        conn: Connection,
        conversation_id: UUID,
        role: str,
        content: str,
        sequence: int,
        cycle: int | None = None,
        time: str | None = None,
        game_date: str | None = None,
        location_ref: str | None = None,
        narrator_deltas: dict | None = None,
    ) -> UUID:
        """Save a message in a conversation."""
        import json as _json

        location_id = await self._resolve_location_id(conn, location_ref)
        deltas_json = _json.dumps(narrator_deltas) if narrator_deltas else None
        return await conn.fetchval(
            """INSERT INTO messages (
                game_id, conversation_id, role, content,
                cycle, game_date, time, location_id, sequence, narrator_deltas
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id""",
            self.game_id,
            conversation_id,
            role,
            content,
            cycle,
            game_date,
            time,
            location_id,
            sequence,
            deltas_json,
        )

    # =========================================================================
    # CHRONOLOGY
    # =========================================================================

    async def save_chronology_entry(
        self,
        conn: Connection,
        cycle: int,
        summary: str,
        time: str | None = None,
        location_ref: str | None = None,
        npc_refs: list[str] | None = None,
    ) -> UUID:
        """Save a chronology entry with optional NPC participants."""
        location_id = await self._resolve_location_id(conn, location_ref)
        entry_id = await conn.fetchval(
            "INSERT INTO chronology (game_id, cycle, time, location_id, summary)"
            " VALUES ($1,$2,$3,$4,$5) RETURNING id",
            self.game_id,
            cycle,
            time,
            location_id,
            summary,
        )

        if npc_refs:
            for npc_ref in npc_refs:
                entity_id = self.registry.resolve(npc_ref)
                if entity_id:
                    await conn.execute(
                        "INSERT INTO chronology_participants"
                        " (chronology_id, entity_id)"
                        " VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        entry_id,
                        entity_id,
                    )
        return entry_id

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_cycle(
        self, conn: Connection, target_cycle: int
    ) -> dict:
        """Rollback via SQL function rollback_to_cycle."""
        result = await conn.fetchrow(
            "SELECT * FROM rollback_to_cycle($1, $2)",
            self.game_id,
            target_cycle,
        )
        stats = {
            "rolled_back_to_cycle": target_cycle,
            "deleted_facts": result["deleted_facts"],
            "deleted_events": result["deleted_events"],
            "deleted_arcs": result["deleted_arcs"],
            "reverted_relations": result["reverted_relations"],
        }
        self.registry.clear()
        await self.load_registry(conn)
        return stats

    # =========================================================================
    # EXTRACTION LOGS
    # =========================================================================

    async def log_extraction(
        self, conn: Connection, cycle: int, stats: dict
    ) -> UUID:
        return await conn.fetchval(
            """INSERT INTO extraction_logs
               (game_id, cycle, facts_created, entities_modified, errors)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            self.game_id,
            cycle,
            stats.get("facts_created", 0),
            stats.get("entities_created", 0) + stats.get("entities_updated", 0),
            json.dumps(stats.get("errors")) if stats.get("errors") else None,
        )

    async def set_extraction_checkpoint(
        self, conn: Connection, extraction_type: str, cycle: int
    ) -> None:
        """Update the per-type extraction checkpoint in games.extraction_checkpoints."""
        await conn.execute(
            """UPDATE games
               SET extraction_checkpoints = COALESCE(extraction_checkpoints, '{}'::jsonb)
                   || jsonb_build_object($2::text, $3::int)
               WHERE id = $1""",
            self.game_id, extraction_type, cycle,
        )
