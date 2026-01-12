"""
LDVELH - Knowledge Graph Reader

Architecture:
- Fonctions génériques pour CRUD simple
- Fonctions spécifiques pour requêtes optimisées/complexes
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Literal
from uuid import UUID

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)

SortOrder = Literal["asc", "desc"]


class KnowledgeGraphReader:
    """Lecteur du Knowledge Graph - SELECT uniquement"""

    def __init__(self, pool: Pool, game_id: UUID | None = None):
        self.pool = pool
        self.game_id = game_id

    # =========================================================================
    # GAMES
    # =========================================================================

    async def list_games(
        self, conn: Connection, active_only: bool = True
    ) -> list[dict]:
        """
        Liste les parties avec métadonnées.
        Requête optimisée avec LEFT JOIN LATERAL au lieu de sous-requête corrélée.
        """
        query = """
            SELECT 
                g.id, g.name, g.active, g.created_at, g.updated_at,
                COALESCE(msg.max_cycle, 0) AS current_cycle,
                cs.date AS current_date
            FROM games g
            LEFT JOIN LATERAL (
                SELECT MAX(cycle) as max_cycle 
                FROM chat_messages WHERE game_id = g.id
            ) msg ON true
            LEFT JOIN LATERAL (
                SELECT date FROM cycle_summaries 
                WHERE game_id = g.id ORDER BY cycle DESC LIMIT 1
            ) cs ON true
        """
        if active_only:
            query += " WHERE g.active = true"
        query += " ORDER BY g.updated_at DESC"

        rows = await conn.fetch(query)
        return [dict(r) for r in rows]

    async def get_game(
        self, conn: Connection, game_id: UUID | None = None
    ) -> dict | None:
        """Récupère une partie par ID"""
        target_id = game_id or self.game_id
        row = await conn.fetchrow(
            "SELECT id, name, active, created_at, updated_at FROM games WHERE id = $1",
            target_id,
        )
        return dict(row) if row else None

    async def game_exists(self, conn: Connection, active_only: bool = True) -> bool:
        """Vérifie si la partie existe"""
        if active_only:
            return await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM games WHERE id = $1 AND active = true)",
                self.game_id,
            )
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM games WHERE id = $1)", self.game_id
        )

    # =========================================================================
    # WORLD STATE
    # =========================================================================

    async def is_world_created(self, conn: Connection) -> bool:
        """Vérifie si le monde est créé (protagoniste existe)"""
        return await conn.fetchval(
            """SELECT EXISTS(
                SELECT 1 FROM entities 
                WHERE game_id = $1 AND type = 'protagonist' AND removed_cycle IS NULL
            )""",
            self.game_id,
        )

    async def get_current_cycle(self, conn: Connection) -> int:
        """Récupère le cycle actuel"""
        result = await conn.fetchval(
            "SELECT COALESCE(MAX(cycle), 0) FROM chat_messages WHERE game_id = $1",
            self.game_id,
        )
        return result or 0

    # =========================================================================
    # ENTITIES - Fonctions de base
    # =========================================================================

    async def get_entity_by_id(self, conn: Connection, entity_id: UUID) -> dict | None:
        """Récupère une entité par ID (optimisé: index primaire)"""
        row = await conn.fetchrow(
            """SELECT id, name, type, aliases, known_by_protagonist, unknown_name,
                      created_cycle, removed_cycle, removal_reason
               FROM entities WHERE id = $1""",
            entity_id,
        )
        return dict(row) if row else None

    async def get_entity_by_name(
        self, conn: Connection, name: str, include_removed: bool = False
    ) -> dict | None:
        """Récupère une entité par nom exact (case-insensitive)"""
        query = """
            SELECT id, name, type, aliases, known_by_protagonist, unknown_name,
                   created_cycle, removed_cycle, removal_reason
            FROM entities 
            WHERE game_id = $1 AND LOWER(name) = LOWER($2)
        """
        if not include_removed:
            query += " AND removed_cycle IS NULL"

        row = await conn.fetchrow(query, self.game_id, name)
        return dict(row) if row else None

    async def find_entity(
        self, conn: Connection, name: str, entity_type: str | None = None
    ) -> UUID | None:
        """Recherche fuzzy via fonction SQL (aliases, préfixes)"""
        return await conn.fetchval(
            "SELECT find_entity($1, $2, $3::entity_type)",
            self.game_id,
            name,
            entity_type,
        )

    async def get_entities(
        self,
        conn: Connection,
        entity_type: str | None = None,
        include_removed: bool = False,
    ) -> list[dict]:
        """Récupère les entités avec filtre optionnel par type"""
        query = "SELECT id, name, type FROM entities WHERE game_id = $1"
        params: list = [self.game_id]

        if not include_removed:
            query += " AND removed_cycle IS NULL"

        if entity_type:
            query += " AND type = $2"
            params.append(entity_type)

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def resolve_entity_refs(
        self, conn: Connection, names: list[str]
    ) -> dict[str, UUID]:
        """Résout plusieurs noms en {name_lower: UUID} - batch optimisé"""
        if not names:
            return {}
        rows = await conn.fetch(
            """SELECT LOWER(name) as name_lower, id FROM entities 
               WHERE game_id = $1 AND LOWER(name) = ANY($2) AND removed_cycle IS NULL""",
            self.game_id,
            [n.lower() for n in names],
        )
        return {r["name_lower"]: r["id"] for r in rows}

    async def get_entity_names_by_ids(
        self, conn: Connection, entity_ids: list[UUID]
    ) -> list[str]:
        """Récupère les noms par IDs - batch optimisé"""
        if not entity_ids:
            return []
        rows = await conn.fetch(
            "SELECT name FROM entities WHERE id = ANY($1)", entity_ids
        )
        return [r["name"] for r in rows]

    async def get_entity_counts_by_type(self, conn: Connection) -> dict[str, int]:
        """Compte les entités actives par type - single query optimisée"""
        row = await conn.fetchrow(
            """SELECT 
                COUNT(*) FILTER (WHERE type = 'character') as characters,
                COUNT(*) FILTER (WHERE type = 'location') as locations,
                COUNT(*) FILTER (WHERE type = 'organization') as organizations,
                COUNT(*) FILTER (WHERE type = 'object') as objects
               FROM entities
               WHERE game_id = $1 AND removed_cycle IS NULL""",
            self.game_id,
        )
        return dict(row) if row else {}

    # =========================================================================
    # ATTRIBUTES
    # =========================================================================

    async def get_attribute(
        self, conn: Connection, entity_id: UUID, key: str
    ) -> str | None:
        """Récupère un attribut via fonction SQL get_attribute"""
        return await conn.fetchval("SELECT get_attribute($1, $2)", entity_id, key)

    async def get_attributes(
        self, conn: Connection, entity_id: UUID, keys: list[str] | None = None
    ) -> dict[str, str]:
        """Récupère plusieurs attributs actifs d'une entité"""
        if keys:
            rows = await conn.fetch(
                """SELECT key, value FROM attributes 
                   WHERE entity_id = $1 AND end_cycle IS NULL AND key = ANY($2)""",
                entity_id,
                keys,
            )
        else:
            rows = await conn.fetch(
                "SELECT key, value FROM attributes WHERE entity_id = $1 AND end_cycle IS NULL",
                entity_id,
            )
        return {r["key"]: r["value"] for r in rows}

    # =========================================================================
    # LOCATIONS
    # =========================================================================

    async def get_root_location(self, conn: Connection) -> dict | None:
        """Récupère la location racine (sans parent) avec attributs"""
        row = await conn.fetchrow(
            """SELECT 
                e.id, e.name,
                get_attribute(e.id, 'location_type') as location_type,
                get_attribute(e.id, 'atmosphere') as atmosphere,
                get_attribute(e.id, 'description') as description,
                get_attribute(e.id, 'notable_features') as notable_features
               FROM entities e
               JOIN entity_locations el ON el.entity_id = e.id
               WHERE e.game_id = $1 
                 AND e.type = 'location' 
                 AND e.removed_cycle IS NULL
                 AND el.parent_location_id IS NULL
               ORDER BY e.created_at ASC
               LIMIT 1""",
            self.game_id,
        )
        return dict(row) if row else None

    # =========================================================================
    # PROTAGONIST / INVENTORY / AI (via vues SQL pré-optimisées)
    # =========================================================================

    async def get_protagonist(self, conn: Connection) -> dict | None:
        """Récupère le protagoniste via vue v_protagonist"""
        row = await conn.fetchrow(
            "SELECT * FROM v_protagonist WHERE game_id = $1", self.game_id
        )
        return dict(row) if row else None

    async def get_protagonist_stats(self, conn: Connection) -> dict | None:
        """Récupère seulement les stats du protagoniste"""
        row = await conn.fetchrow(
            "SELECT energy, morale, health, credits FROM v_protagonist WHERE game_id = $1",
            self.game_id,
        )
        return dict(row) if row else None

    async def get_inventory(self, conn: Connection) -> list[dict]:
        """Récupère l'inventaire via vue v_inventory"""
        rows = await conn.fetch(
            "SELECT * FROM v_inventory WHERE game_id = $1", self.game_id
        )
        return [dict(r) for r in rows]

    async def get_ai_companion(self, conn: Connection) -> dict | None:
        """Récupère l'IA compagnon via vue v_ais"""
        row = await conn.fetchrow(
            "SELECT * FROM v_ais WHERE game_id = $1 LIMIT 1", self.game_id
        )
        return dict(row) if row else None

    # =========================================================================
    # MESSAGES
    # =========================================================================

    async def get_message(self, conn: Connection, message_id: UUID) -> dict | None:
        """Récupère un message par ID"""
        row = await conn.fetchrow(
            """SELECT id, role, content, cycle, time, date, 
                      location_id, npcs_present, summary, created_at
               FROM chat_messages WHERE id = $1 AND game_id = $2""",
            message_id,
            self.game_id,
        )
        return dict(row) if row else None

    async def get_messages(
        self,
        conn: Connection,
        limit: int | None = None,
        order: SortOrder = "asc",
    ) -> list[dict]:
        """Récupère les messages (chronologique par défaut)"""
        query = """
            SELECT id, role, content, cycle, time, date, 
                   location_id, npcs_present, summary, created_at
            FROM chat_messages WHERE game_id = $1
            ORDER BY created_at
        """
        query = query.replace(
            "ORDER BY created_at", f"ORDER BY created_at {order.upper()}"
        )

        if limit:
            query += f" LIMIT {int(limit)}"  # int() pour sécurité

        rows = await conn.fetch(query, self.game_id)
        return [dict(r) for r in rows]

    async def get_last_assistant_message(self, conn: Connection) -> dict | None:
        """Récupère le dernier message assistant avec nom du lieu - requête optimisée"""
        row = await conn.fetchrow(
            """SELECT m.id, m.cycle, m.date, m.time, m.location_id, m.npcs_present,
                      e.name as location_name
               FROM chat_messages m
               LEFT JOIN entities e ON e.id = m.location_id
               WHERE m.game_id = $1 AND m.role = 'assistant'
               ORDER BY m.created_at DESC LIMIT 1""",
            self.game_id,
        )
        return dict(row) if row else None

    async def get_message_count(self, conn: Connection) -> int:
        """Compte les messages"""
        return await conn.fetchval(
            "SELECT COUNT(*) FROM chat_messages WHERE game_id = $1", self.game_id
        )

    # =========================================================================
    # CYCLE SUMMARIES
    # =========================================================================

    async def get_cycle_summary(self, conn: Connection, cycle: int) -> dict | None:
        """Récupère le résumé d'un cycle spécifique"""
        row = await conn.fetchrow(
            """SELECT id, cycle, date, summary, key_events, modified_relations
               FROM cycle_summaries WHERE game_id = $1 AND cycle = $2""",
            self.game_id,
            cycle,
        )
        return dict(row) if row else None

    async def get_latest_cycle_summary(self, conn: Connection) -> dict | None:
        """Récupère le dernier résumé de cycle"""
        row = await conn.fetchrow(
            """SELECT id, cycle, date, summary, key_events, modified_relations
               FROM cycle_summaries 
               WHERE game_id = $1 ORDER BY cycle DESC LIMIT 1""",
            self.game_id,
        )
        return dict(row) if row else None

    async def get_arrival_event(self, conn: Connection) -> dict | None:
        """Récupère les événements d'arrivée (cycle 1) avec parsing JSON"""
        row = await conn.fetchrow(
            "SELECT date, key_events FROM cycle_summaries WHERE game_id = $1 AND cycle = 1",
            self.game_id,
        )
        if not row or not row["key_events"]:
            return None

        events = row["key_events"]
        if isinstance(events, str):
            events = json.loads(events)

        return {"date": row["date"], "events": events}

    async def get_current_date(self, conn: Connection) -> str | None:
        """Récupère la date actuelle du jeu"""
        return await conn.fetchval(
            """SELECT date FROM cycle_summaries 
               WHERE game_id = $1 ORDER BY cycle DESC LIMIT 1""",
            self.game_id,
        )

    # =========================================================================
    # RELATIONS - Requête optimisée avec JOIN
    # =========================================================================

    async def get_relations(
        self,
        conn: Connection,
        entity_id: UUID | None = None,
        relation_type: str | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        """Récupère les relations d'une entité"""
        query = """
            SELECT r.id, r.source_id, r.target_id, r.type, r.known_by_protagonist,
                   r.start_cycle, r.end_cycle,
                   src.name as source_name, tgt.name as target_name
            FROM relations r
            JOIN entities src ON src.id = r.source_id
            JOIN entities tgt ON tgt.id = r.target_id
            WHERE r.game_id = $1
        """
        params: list = [self.game_id]

        if active_only:
            query += " AND r.end_cycle IS NULL"

        if entity_id:
            query += f" AND (r.source_id = ${len(params) + 1} OR r.target_id = ${len(params) + 1})"
            params.append(entity_id)

        if relation_type:
            query += f" AND r.type = ${len(params) + 1}"
            params.append(relation_type)

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_relation_between(
        self,
        conn: Connection,
        source_id: UUID,
        target_id: UUID,
        relation_type: str | None = None,
        active_only: bool = True,
    ) -> dict | None:
        """Récupère une relation entre deux entités (par IDs, pas refs)"""
        query = """
            SELECT r.*, src.name as source_name, tgt.name as target_name
            FROM relations r
            JOIN entities src ON src.id = r.source_id
            JOIN entities tgt ON tgt.id = r.target_id
            WHERE r.game_id = $1 AND r.source_id = $2 AND r.target_id = $3
        """
        params: list = [self.game_id, source_id, target_id]

        if active_only:
            query += " AND r.end_cycle IS NULL"

        if relation_type:
            query += " AND r.type = $4"
            params.append(relation_type)

        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    # =========================================================================
    # FACTS
    # =========================================================================

    async def get_facts(
        self,
        conn: Connection,
        cycle: int | None = None,
        limit: int | None = None,
        order: SortOrder = "desc",
    ) -> list[dict]:
        """Récupère les faits avec filtres"""
        query = """
            SELECT id, cycle, type as fact_type, description, location_id, 
                   time, importance, semantic_key, created_at
            FROM facts WHERE game_id = $1
        """
        params: list = [self.game_id]

        if cycle is not None:
            query += f" AND cycle = ${len(params) + 1}"
            params.append(cycle)

        query += f" ORDER BY cycle {order.upper()}, created_at {order.upper()}"

        if limit:
            query += f" LIMIT {int(limit)}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def fact_exists(
        self, conn: Connection, cycle: int, semantic_key: str
    ) -> bool:
        """Vérifie si un fait existe (utilise l'index unique)"""
        return await conn.fetchval(
            """SELECT EXISTS(
                SELECT 1 FROM facts 
                WHERE game_id = $1 AND cycle = $2 AND semantic_key = $3
            )""",
            self.game_id,
            cycle,
            semantic_key,
        )

    # =========================================================================
    # COMMITMENTS & EVENTS
    # =========================================================================

    async def get_commitments(
        self, conn: Connection, active_only: bool = True
    ) -> list[dict]:
        """Récupère les engagements"""
        query = """
            SELECT id, type, description, created_cycle, deadline_cycle, resolved
            FROM commitments WHERE game_id = $1
        """
        if active_only:
            query += " AND resolved = false"
        query += " ORDER BY deadline_cycle ASC NULLS LAST"

        rows = await conn.fetch(query, self.game_id)
        return [dict(r) for r in rows]

    async def get_events(
        self,
        conn: Connection,
        from_cycle: int | None = None,
        limit: int | None = None,
        pending_only: bool = True,
    ) -> list[dict]:
        """Récupère les événements planifiés"""
        query = """
            SELECT id, title, description, planned_cycle, 
                   time, location_id, type, completed, cancelled
            FROM events WHERE game_id = $1
        """
        params: list = [self.game_id]

        if pending_only:
            query += " AND completed = false AND cancelled = false"

        if from_cycle is not None:
            query += f" AND planned_cycle >= ${len(params) + 1}"
            params.append(from_cycle)

        query += " ORDER BY planned_cycle ASC"

        if limit:
            query += f" LIMIT {int(limit)}"

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
