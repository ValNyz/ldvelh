"""
LDVELH - Knowledge Graph Populator (Dedicated Tables Architecture)
Write operations for all game data tables.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from config import get_identity_config
from schema import (
    CompanionData,
    EntityType,
    FactData,
    NarrativeArcData,
    ProtagonistData,
    RelationType,
    Skill,
)
from schema.entity_changes import CHANGES_MODELS, bound_changes

from .upsert_sql import TEXT, non_blank

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

    from services.identity.service import IdentityService

logger = logging.getLogger(__name__)

# Domain table of each entity type an update or a removal writes.
_TABLES = {
    EntityType.CHARACTER: "characters",
    EntityType.LOCATION: "locations",
    EntityType.ORGANIZATION: "organizations",
    EntityType.OBJECT: "objects",
}


class KnowledgeGraphPopulator:
    """Write operations for the dedicated tables architecture, by entity id.

    Every entity is created by IdentityService.create_entity and every reference made of
    words is resolved before it reaches a method here (kg.refs); the methods take ids.
    """

    def __init__(self, pool: Pool, game_id: UUID | None = None):
        self.pool = pool
        self.game_id = game_id
        self._identity: IdentityService | None = None

    async def identity(self, conn: Connection) -> IdentityService:
        """The game's identity service, built once (its language packs loaded once per
        populator, not per item)."""
        if self._identity is None:
            # Lazy: the service imports repos.uow, which imports repos.turns -> this module.
            from services.identity.service import IdentityService

            self._identity = await IdentityService.for_game(conn, self.game_id)
        return self._identity

    # =========================================================================
    # GAMES
    # =========================================================================

    async def create_game(
        self,
        conn: Connection,
        name: str = "Nouvelle partie",
        user_id: UUID | None = None,
    ) -> UUID:
        """Create a new game. user_id required by DB (NOT NULL). Its language (the pack its
        entity names are normalised with) is the configured default."""
        self.game_id = await conn.fetchval(
            "INSERT INTO games (user_id, name, language) VALUES ($1, $2, $3) RETURNING id",
            user_id,
            name,
            get_identity_config().default_language,
        )
        logger.info(f"Created game {self.game_id}: {name}")
        return self.game_id

    async def delete_game(self, conn: Connection, game_id: UUID | None = None) -> bool:
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
        await conn.execute(f"UPDATE games SET {', '.join(sets)} WHERE id = $1", *params)

    async def create_stub_event(
        self, conn: Connection, event_hint, cycle: int, location_id: UUID | None = None
    ) -> None:
        """Create a stub event from narrator EventHint (formalized at extraction time);
        `location_id`: its place, resolved by the caller."""
        # Avoid duplicates by title + planned_cycle
        planned_cycle = event_hint.planned_cycle or cycle + 1
        existing = await conn.fetchval(
            "SELECT id FROM events WHERE game_id=$1 AND title=$2 AND planned_cycle=$3",
            self.game_id,
            event_hint.title,
            planned_cycle,
        )
        if not existing:
            await conn.execute(
                """INSERT INTO events (game_id, title, type, planned_cycle, time, location_id)
                VALUES ($1, $2, 'appointment', $3, $4, $5)""",
                self.game_id,
                event_hint.title,
                planned_cycle,
                event_hint.planned_time,
                location_id,
            )
            # The title is story text: only the cycle is logged.
            logger.info(f"[KG] Created stub event (cycle {planned_cycle})")

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

    async def protagonist_id(self, conn: Connection) -> UUID | None:
        return await conn.fetchval(
            "SELECT id FROM protagonists WHERE game_id = $1", self.game_id
        )

    # =========================================================================
    # PROTAGONIST AND COMPANION (made by game creation; the triggers register them)
    # =========================================================================

    async def create_protagonist(self, conn: Connection, data: ProtagonistData) -> UUID:
        """Insert protagonist into dedicated table."""
        reason = (
            data.departure_reason.value
            if hasattr(data.departure_reason, "value")
            else str(data.departure_reason)
        )
        row_id = await conn.fetchval(
            """INSERT INTO protagonists (
                game_id, name, credits,
                gender, occupation, origin, departure_reason, backstory,
                hobbies, description, details
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            RETURNING id""",
            self.game_id,
            data.name,
            data.credits,
            data.gender,
            data.occupation,
            data.origin,
            reason,
            data.backstory,
            data.hobbies,
            data.description,
            data.details if data.details else {},
        )
        for skill in data.skills:
            await self._insert_skill(conn, skill, protagonist_id=row_id)
        return row_id

    async def create_companion(self, conn: Connection, data: CompanionData) -> UUID:
        """Insert companion into dedicated table."""
        return await conn.fetchval(
            """INSERT INTO companions (
                game_id, name, voice, traits, quirk, substrate, details
            ) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
            self.game_id,
            data.name,
            data.voice,
            data.traits,
            data.quirk,
            data.substrate or "terminal personnel",
            data.details if data.details else {},
        )

    # =========================================================================
    # ENTITY UPDATES
    # =========================================================================

    async def update_entity(
        self,
        conn: Connection,
        entity_id: UUID,
        entity_type: EntityType,
        fields: dict,
        *,
        turn_id: UUID | None = None,
    ) -> bool:
        """Write extracted field changes on an entity, by id (IdentityService.update_entity:
        merges followed, a missing row raises IdentityWriteMiss).

        Only the columns typed in schema.entity_changes are written, each bounded to its
        column (an invalid field is dropped, the others are kept): every extracted update
        (entity updates, ambient updates) reaches SQL here, so this is the one place they
        are bounded. known_by_protagonist is a reveal's, never written here. False when
        nothing is left to write (or the type takes no extracted changes).
        """
        if entity_type not in CHANGES_MODELS:
            logger.info(f"[UPDATE] {entity_type} takes no extracted changes")
            return False
        bounded = bound_changes(entity_type, fields)
        bounded.pop("known_by_protagonist", None)
        if not bounded:
            return False
        identity = await self.identity(conn)
        await identity.update_entity(
            conn,
            entity_id,
            entity_type.value,
            bounded,
            source="extractor",
            turn_id=turn_id,
        )
        return True

    async def remove_entity(
        self,
        conn: Connection,
        entity_id: UUID,
        entity_type: EntityType,
        cycle: int,
    ) -> bool:
        """Mark an entity as removed (removed_cycle), by id; False when it already was."""
        table = _TABLES.get(entity_type)
        if not table:
            return False
        result = await conn.execute(
            f"UPDATE {table} SET removed_cycle = $1, updated_at = NOW()"
            f" WHERE game_id = $2 AND id = $3 AND removed_cycle IS NULL",
            cycle,
            self.game_id,
            entity_id,
        )
        return result != "UPDATE 0"

    async def is_live(
        self, conn: Connection, entity_type: EntityType, entity_id: UUID
    ) -> bool:
        """The entity exists and was not removed from the world."""
        return bool(
            await conn.fetchval(
                f"SELECT EXISTS (SELECT 1 FROM {_TABLES[entity_type]}"
                " WHERE id = $1 AND game_id = $2 AND removed_cycle IS NULL)",
                entity_id,
                self.game_id,
            )
        )

    async def mark_location_accessible(
        self, conn: Connection, location_id: UUID
    ) -> bool:
        """Mark a location as accessible, by id."""
        result = await conn.execute(
            "UPDATE locations SET accessible = true, updated_at = NOW()"
            " WHERE id = $1 AND game_id = $2",
            location_id,
            self.game_id,
        )
        return result != "UPDATE 0"

    # =========================================================================
    # RELATIONS
    # =========================================================================

    async def create_relation(
        self,
        conn: Connection,
        source_id: UUID,
        target_id: UUID,
        relation_type: RelationType,
        cycle: int = 1,
        *,
        level: int | None = None,
        context: str | None = None,
        known_by_protagonist: bool = True,
    ) -> UUID | None:
        """Create or update a relation between two entities (SQL upsert_relation)."""
        return await conn.fetchval(
            "SELECT upsert_relation($1, $2, $3, $4::relation_type, $5, $6, $7, $8)",
            self.game_id,
            source_id,
            target_id,
            relation_type.value,
            cycle,
            level,
            context,
            known_by_protagonist,
        )

    async def end_relation(
        self,
        conn: Connection,
        source_id: UUID,
        target_id: UUID,
        relation_type: RelationType,
        cycle: int,
        reason: str | None = None,
    ) -> bool:
        """End the active relation between two entities (SQL end_relation).

        Raises LookupError when no active relation matched, so a per-item savepoint
        records the failure. The message is constant (no story text).
        """
        ended = await conn.fetchval(
            "SELECT end_relation($1, $2, $3, $4::relation_type, $5, $6)",
            self.game_id,
            source_id,
            target_id,
            relation_type.value,
            cycle,
            reason,
        )
        if not ended:
            raise LookupError("no active relation matched the end")
        return True

    # =========================================================================
    # FACTS
    # =========================================================================

    async def create_fact(
        self,
        conn: Connection,
        fact: FactData,
        participants: list[tuple[UUID, str]],
        location_id: UUID | None = None,
    ) -> UUID | None:
        """Create a fact via SQL function create_fact (with deduplication).
        `participants`: (entity id, role) pairs; the references of `fact` are not read."""
        fact_id = await conn.fetchval(
            "SELECT create_fact($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)",
            self.game_id,
            fact.cycle,
            fact.fact_type.value,
            fact.description,
            location_id,
            fact.time,
            fact.importance,
            [
                {"entity_id": str(entity_id), "role": role}
                for entity_id, role in participants
            ],
            fact.semantic_key,
        )
        if fact_id:
            logger.info(f"[FACT] Created {fact_id} ({fact.fact_type.value})")
            logger.debug(f"[FACT] {fact_id} key: {fact.semantic_key}")
        return fact_id

    # =========================================================================
    # PROTAGONIST — Credits
    # =========================================================================

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
            f" AND LOWER(skills.name) = LOWER($4) AND end_cycle IS NULL",
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
        self,
        conn: Connection,
        arc: NarrativeArcData,
        cycle: int,
        participant_ids: list[UUID],
        owner_id: UUID | None = None,
    ) -> UUID:
        """Create a narrative arc with its participants, by id (dedup by title).

        `cycle` stamps a new arc's created_cycle (rollback deletes by it, #85);
        an arc that already exists keeps its own, and keeps its intensity unless `arc`
        sets one explicitly (a re-listed arc must not fall back to the default, #87).
        The references of `arc` are not read: the caller resolved them.
        """
        domain = arc.domain if isinstance(arc.domain, str) else str(arc.domain)

        # Dedup: check for existing arc with same title
        existing_id = await conn.fetchval(
            "SELECT id FROM narrative_arcs"
            " WHERE game_id = $1 AND LOWER(title) = LOWER($2)"
            " AND resolved = false",
            self.game_id,
            arc.title,
        )
        if existing_id:
            # The title is story text: only the id is logged.
            logger.info(f"[ARC] Arc {existing_id} already exists, updating instead")
            await conn.execute(
                f"""UPDATE narrative_arcs SET
                    description = COALESCE({non_blank("$3", TEXT)}, description),
                    intensity = COALESCE($4, intensity), updated_at = NOW()
                WHERE id = $2 AND game_id = $1""",
                self.game_id,
                existing_id,
                arc.description,
                arc.intensity if "intensity" in arc.model_fields_set else None,
            )
            arc_id = existing_id
        else:
            arc_id = await conn.fetchval(
                """INSERT INTO narrative_arcs (
                    game_id, title, domain, description, intensity, owner_id,
                    created_cycle
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                RETURNING id""",
                self.game_id,
                arc.title,
                domain,
                arc.description,
                arc.intensity,
                owner_id,
                cycle,
            )

        for entity_id in participant_ids:
            await conn.execute(
                "INSERT INTO arc_participants (arc_id, entity_id, role)"
                " VALUES ($1, $2, 'involved') ON CONFLICT DO NOTHING",
                arc_id,
                entity_id,
            )
        return arc_id

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
        location_id: UUID | None = None,
        completed: bool = False,
    ) -> UUID:
        """Create a scheduled event; `location_id`: its place, resolved by the caller."""
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

    async def create_conversation(self, conn: Connection, start_cycle: int) -> UUID:
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
        location_id: UUID | None = None,
        narrator_deltas: dict | None = None,
        engine_snapshot: dict | None = None,
        narrator_context: list | None = None,
        turn_id: UUID | None = None,
    ) -> UUID:
        """Save a message in a conversation; `location_id`: the place of the turn."""
        return await conn.fetchval(
            """INSERT INTO messages (
                game_id, conversation_id, role, content,
                cycle, game_date, time, location_id, sequence,
                narrator_deltas, engine_snapshot, narrator_context, turn_id
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id""",
            self.game_id,
            conversation_id,
            role,
            content,
            cycle,
            game_date,
            time,
            location_id,
            sequence,
            narrator_deltas,
            engine_snapshot,
            narrator_context,
            turn_id,
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
        location_id: UUID | None = None,
        npc_ids: list[UUID] | None = None,
    ) -> UUID:
        """Save a chronology entry with its participants, by id."""
        entry_id = await conn.fetchval(
            "INSERT INTO chronology (game_id, cycle, time, location_id, summary)"
            " VALUES ($1,$2,$3,$4,$5) RETURNING id",
            self.game_id,
            cycle,
            time,
            location_id,
            summary,
        )
        for entity_id in npc_ids or ():
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

    async def rollback_to_cycle(self, conn: Connection, target_cycle: int) -> dict:
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
        return stats

    # =========================================================================
    # NARRATIVE SEEDS
    # =========================================================================

    async def save_seed(
        self, conn: Connection, cycle: int, text: str, location_id=None
    ):
        """Store a narrative seed."""
        await conn.execute(
            """INSERT INTO narrative_seeds (game_id, cycle, text, location_id)
               VALUES ($1, $2, $3, $4)""",
            self.game_id,
            cycle,
            text,
            location_id,
        )

    async def archive_stale_seeds(
        self, conn: Connection, current_cycle: int, max_age: int = 10
    ):
        """Archive seeds older than max_age cycles."""
        await conn.execute(
            """UPDATE narrative_seeds SET status = 'archived'
               WHERE game_id = $1 AND status = 'active'
                 AND cycle < $2""",
            self.game_id,
            current_cycle - max_age,
        )

    async def crystallize_seed(self, conn: Connection, seed_id, arc_id):
        """Mark a seed as crystallized into an arc."""
        await conn.execute(
            """UPDATE narrative_seeds SET status = 'crystallized', crystallized_arc_id = $1
               WHERE id = $2""",
            arc_id,
            seed_id,
        )

    # =========================================================================
    # EXTRACTION LOGS
    # =========================================================================

    async def log_extraction(
        self, conn: Connection, cycle: int, stats: dict, turn_id: UUID | None = None
    ) -> UUID:
        """Audit row of one extraction; `turn_id` ties it to its turn (deleted with it)."""
        return await conn.fetchval(
            """INSERT INTO extraction_logs
               (game_id, cycle, facts_created, entities_modified, errors, turn_id)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            self.game_id,
            cycle,
            stats.get("facts_created", 0),
            stats.get("entities_created", 0) + stats.get("entities_updated", 0),
            stats.get("errors"),
            turn_id,
        )

    # =========================================================================
    # ENGINE
    # =========================================================================

    async def lock_engine(self, conn: Connection) -> None:
        """Lock the engine (immutable after first message)."""
        await conn.execute(
            "UPDATE games SET engine_locked = TRUE, updated_at = NOW() WHERE id = $1",
            self.game_id,
        )

    async def log_mechanic_roll(
        self,
        conn: Connection,
        game_id: UUID,
        message_id: UUID | None,
        engine: str,
        skill_used: str | None,
        roll_details: dict,
        outcome: str,
        complication: bool,
        cycle: int | None,
        turn_id: UUID | None = None,
    ) -> UUID:
        """Insert a mechanic roll log entry."""
        return await conn.fetchval(
            """INSERT INTO mechanic_rolls
               (game_id, message_id, engine, skill_used,
                roll_details, outcome, complication, cycle, turn_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING id""",
            game_id,
            message_id,
            engine,
            skill_used,
            roll_details,
            outcome,
            complication,
            cycle,
            turn_id,
        )
