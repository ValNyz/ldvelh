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

    async def get_date_for_cycle(self, conn: Connection, cycle: int) -> str | None:
        """Récupère la date pour un cycle donné"""
        return await conn.fetchval(
            """SELECT date FROM cycle_summaries 
               WHERE game_id = $1 AND cycle <= $2 
               ORDER BY cycle DESC LIMIT 1""",
            self.game_id,
            cycle,
        )

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
    # CHARACTER
    # =========================================================================

    async def get_known_characters(self, conn: Connection) -> list[dict]:
        """
        Récupère les PNJs connus du protagoniste via v_characters_context.
        Inclut la localisation via v_active_relations.
        Triés par niveau de relation décroissant.
        """
        rows = await conn.fetch(
            """
            SELECT 
                cc.entity_id as id,
                cc.name,
                cc.species,
                cc.gender,
                cc.physical_description,
                cc.traits,
                cc.current_position as profession,
                cc.mood,
                cc.relation_level,
                cc.relation_context,
                (SELECT ar.target_name 
                 FROM v_active_relations ar
                 WHERE ar.source_id = cc.entity_id
                   AND ar.relation_type IN ('works_at', 'lives_at', 'frequents')
                 LIMIT 1) as location
            FROM v_characters_context cc
            WHERE cc.game_id = $1
            ORDER BY COALESCE(cc.relation_level, 0) DESC, cc.name ASC
            """,
            self.game_id,
        )
        return [dict(r) for r in rows]

    async def get_character_location(
        self, conn: Connection, character_id: UUID
    ) -> str | None:
        """Récupère le lieu associé à un personnage (works_at, lives_at, frequents)"""
        return await conn.fetchval(
            """
            SELECT target_name FROM v_active_relations
            WHERE game_id = $1 
              AND source_id = $2
              AND relation_type IN ('works_at', 'lives_at', 'frequents')
            LIMIT 1
            """,
            self.game_id,
            character_id,
        )

    async def get_top_related_npcs(
        self, conn: Connection, limit: int = 5
    ) -> list[dict]:
        """Récupère les NPCs avec la meilleure relation (triés par level)"""
        rows = await conn.fetch(
            """SELECT 
                cc.entity_id as id, cc.name, cc.species,
                cc.physical_description, cc.traits, cc.current_position as occupation,
                cc.mood, cc.relation_level as rel_level, cc.relation_context as rel_context,
                get_attribute(cc.entity_id, 'arcs') as arcs,
                e.known_by_protagonist, e.unknown_name
               FROM v_characters_context cc
               JOIN entities e ON e.id = cc.entity_id
               WHERE cc.game_id = $1 AND cc.relation_level IS NOT NULL
               ORDER BY cc.relation_level DESC
               LIMIT $2""",
            self.game_id,
            limit,
        )
        return [dict(r) for r in rows]

    # =========================================================================
    # ORGANIZATIONS
    # =========================================================================

    async def get_known_organizations(self, conn: Connection) -> list[dict]:
        """
        Récupère les organisations connues du protagoniste.
        Utilise v_active_relations pour la relation avec le protagoniste.
        """
        rows = await conn.fetch(
            """
            SELECT 
                e.id,
                e.name,
                eo.org_type,
                eo.domain,
                eo.size,
                (SELECT ar.relation_type::text 
                 FROM v_active_relations ar 
                 WHERE ar.target_id = e.id 
                   AND ar.source_type = 'protagonist'
                 LIMIT 1) as protagonist_relation
            FROM entities e
            JOIN entity_organizations eo ON eo.entity_id = e.id
            WHERE e.game_id = $1 
              AND e.type = 'organization'
              AND e.removed_cycle IS NULL
              AND e.known_by_protagonist = true
            ORDER BY e.name ASC
            """,
            self.game_id,
        )
        return [dict(r) for r in rows]

    # =========================================================================
    # LOCATIONS
    # =========================================================================

    async def get_location_details(self, conn: Connection, name: str) -> dict | None:
        """Récupère une location par nom avec ses attributs"""
        row = await conn.fetchrow(
            """SELECT 
                e.id, e.name,
                get_attribute(e.id, 'location_type') as location_type,
                get_attribute(e.id, 'sector') as sector,
                get_attribute(e.id, 'atmosphere') as atmosphere,
                COALESCE(get_attribute(e.id, 'accessible'), 'true')::BOOLEAN as accessible
               FROM entities e
               WHERE e.game_id = $1 AND e.type = 'location' 
                 AND LOWER(e.name) = LOWER($2) AND e.removed_cycle IS NULL""",
            self.game_id,
            name,
        )
        return dict(row) if row else None

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

    async def get_sibling_locations(
        self, conn: Connection, location_name: str, limit: int = 10
    ) -> list[dict]:
        """
        Récupère les locations accessibles (même secteur ou accessibles).
        Optimisé avec une seule requête.
        """
        rows = await conn.fetch(
            """WITH current AS (
                SELECT e.id, get_attribute(e.id, 'sector') as sector
                FROM entities e
                WHERE e.game_id = $1 AND LOWER(e.name) = LOWER($2) AND e.type = 'location'
            )
            SELECT e.name,
                   get_attribute(e.id, 'location_type') as location_type,
                   get_attribute(e.id, 'sector') as sector,
                   get_attribute(e.id, 'atmosphere') as atmosphere
            FROM entities e, current c
            WHERE e.game_id = $1 
              AND e.type = 'location'
              AND e.removed_cycle IS NULL
              AND e.known_by_protagonist = true
              AND e.id != c.id
              AND (
                  COALESCE(get_attribute(e.id, 'accessible'), 'true')::BOOLEAN = true
                  OR get_attribute(e.id, 'sector') = c.sector
              )
            LIMIT $3""",
            self.game_id,
            location_name,
            limit,
        )
        return [dict(r) for r in rows]

    async def get_known_locations(self, conn: Connection) -> list[dict]:
        """
        Récupère les lieux connus du protagoniste.
        Utilise v_active_relations pour déterminer si visité.
        """
        rows = await conn.fetch(
            """
            SELECT 
                e.id,
                e.name,
                el.location_type,
                el.sector,
                el.accessible,
                (SELECT ep.name FROM entities ep 
                 WHERE ep.id = el.parent_location_id) as parent_name,
                EXISTS(
                    SELECT 1 FROM v_active_relations ar
                    WHERE ar.target_id = e.id
                      AND ar.source_type = 'protagonist'
                      AND ar.relation_type IN ('frequents', 'works_at', 'lives_at')
                ) as visited
            FROM entities e
            JOIN entity_locations el ON el.entity_id = e.id
            WHERE e.game_id = $1 
              AND e.type = 'location'
              AND e.removed_cycle IS NULL
              AND e.known_by_protagonist = true
            ORDER BY el.sector NULLS LAST, e.name ASC
            """,
            self.game_id,
        )
        return [dict(r) for r in rows]

    async def get_npcs_at_location(
        self, conn: Connection, location_name: str
    ) -> list[dict]:
        """Récupère les NPCs présents à une location via leurs relations spatiales"""
        rows = await conn.fetch(
            """SELECT 
                e.id, e.name, e.known_by_protagonist, e.unknown_name,
                get_attribute(e.id, 'occupation') as occupation,
                get_attribute(e.id, 'species') as species,
                get_attribute(e.id, 'traits') as traits,
                get_attribute(e.id, 'arcs') as arcs,
                rs.context as rel_context,
                rs.level as rel_level
               FROM entities e
               JOIN relations r ON r.source_id = e.id AND r.end_cycle IS NULL
               JOIN entities loc ON loc.id = r.target_id
               LEFT JOIN relations r_proto ON r_proto.target_id = e.id 
                   AND r_proto.type = 'knows' AND r_proto.end_cycle IS NULL
                   AND r_proto.source_id = (
                       SELECT id FROM entities WHERE type = 'protagonist' AND game_id = $1 LIMIT 1
                   )
               LEFT JOIN relations_social rs ON rs.relation_id = r_proto.id
               WHERE e.game_id = $1 
                 AND e.type = 'character'
                 AND e.removed_cycle IS NULL
                 AND r.type IN ('works_at', 'frequents', 'lives_at')
                 AND LOWER(loc.name) = LOWER($2)""",
            self.game_id,
            location_name,
        )
        return [dict(r) for r in rows]

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

    async def get_protagonist_with_skills(self, conn: Connection) -> dict | None:
        """
        Récupère le protagoniste avec skills et employer.
        Étend v_protagonist avec des données relationnelles.
        """
        result = await self.get_protagonist(conn)
        if not result:
            return None

        # Skills (pas dans la vue)
        skills = await conn.fetch(
            """SELECT name, level FROM skills 
               WHERE entity_id = $1 AND end_cycle IS NULL""",
            result["id"],
        )
        result["skills"] = [dict(s) for s in skills]

        # Employer via relation
        result["employer"] = await conn.fetchval(
            """SELECT e.name FROM relations r
               JOIN entities e ON e.id = r.target_id
               WHERE r.source_id = $1 AND r.type = 'employed_by' AND r.end_cycle IS NULL
               LIMIT 1""",
            result["id"],
        )

        return result

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

    async def get_message_summaries(
        self, conn: Connection, limit: int = 5
    ) -> list[dict]:
        """Récupère les résumés des messages récents (avec summary non null)"""
        rows = await conn.fetch(
            """SELECT role, summary, cycle
               FROM chat_messages 
               WHERE game_id = $1 AND summary IS NOT NULL
               ORDER BY created_at DESC
               LIMIT $2""",
            self.game_id,
            limit,
        )
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

    async def get_cycle_summaries(
        self, conn: Connection, max_cycle: int, limit: int = 7
    ) -> list[dict]:
        """Récupère les résumés des N derniers cycles"""
        rows = await conn.fetch(
            """SELECT cycle, date, summary, key_events
               FROM cycle_summaries 
               WHERE game_id = $1 AND cycle <= $2
               ORDER BY cycle DESC
               LIMIT $3""",
            self.game_id,
            max_cycle,
            limit,
        )
        return [dict(r) for r in rows]

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
    # RELATIONS
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

    async def get_facts_with_participants(
        self,
        conn: Connection,
        cycle: int | None = None,
        min_importance: int = 1,
        location_name: str | None = None,
        npc_names: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Récupère les faits avec participants (requête unifiée).
        Remplace get_important_facts, get_location_facts, get_npc_facts.
        """
        query = """
            SELECT 
                f.id, f.cycle, f.type as fact_type, f.description, 
                f.importance, f.time,
                (SELECT array_agg(jsonb_build_object('name', e.name, 'role', fp.role))
                 FROM fact_participants fp
                 JOIN entities e ON fp.entity_id = e.id
                 WHERE fp.fact_id = f.id) as participants
            FROM facts f
            WHERE f.game_id = $1 AND f.importance >= $2
        """
        params: list = [self.game_id, min_importance]

        if cycle is not None:
            params.append(cycle)
            query += f" AND f.cycle <= ${len(params)}"

        if location_name:
            params.append(location_name.lower())
            query += f""" AND f.location_id = (
                SELECT id FROM entities 
                WHERE game_id = $1 AND LOWER(name) = ${len(params)} AND type = 'location'
            )"""

        if npc_names:
            params.append([n.lower() for n in npc_names])
            query += f""" AND f.id IN (
                SELECT fp.fact_id FROM fact_participants fp
                JOIN entities e ON fp.entity_id = e.id
                WHERE LOWER(e.name) = ANY(${len(params)})
            )"""

        query += " ORDER BY f.importance DESC, f.cycle DESC"
        params.append(limit)
        query += f" LIMIT ${len(params)}"

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

    async def get_commitments_detailed(self, conn: Connection) -> list[dict]:
        """Récupère les commitments actifs avec entités impliquées"""
        rows = await conn.fetch(
            """SELECT 
                c.id, c.type, c.description, c.created_cycle, c.deadline_cycle,
                ca.objective, ca.obstacle, ca.progress,
                (SELECT array_agg(jsonb_build_object('name', e.name, 'role', ce.role))
                 FROM commitment_entities ce
                 JOIN entities e ON ce.entity_id = e.id
                 WHERE ce.commitment_id = c.id) as entities
               FROM commitments c
               LEFT JOIN commitment_arcs ca ON ca.commitment_id = c.id
               WHERE c.game_id = $1 AND c.resolved = false
               ORDER BY c.deadline_cycle NULLS LAST""",
            self.game_id,
        )
        return [dict(r) for r in rows]

    async def get_active_commitments(self, conn: Connection) -> list[dict]:
        """
        Récupère les quêtes/arcs actifs via v_active_commitments.
        """
        rows = await conn.fetch(
            """
            SELECT 
                id,
                type,
                description,
                created_cycle,
                deadline_cycle,
                objective,
                obstacle,
                progress,
                entities
            FROM v_active_commitments
            WHERE game_id = $1
            ORDER BY 
                CASE type 
                    WHEN 'arc' THEN 1 
                    WHEN 'secret' THEN 2 
                    WHEN 'chekhov_gun' THEN 3
                    ELSE 4 
                END,
                deadline_cycle NULLS LAST
            """,
            self.game_id,
        )
        return [dict(r) for r in rows]

    async def find_commitment_by_description(
        self, conn: Connection, description: str
    ) -> dict | None:
        """Trouve un commitment par description partielle (pour résolution)"""
        row = await conn.fetchrow(
            """SELECT id, type, description, resolved
               FROM commitments 
               WHERE game_id = $1 AND resolved = false
                 AND description ILIKE '%' || $2 || '%'
               LIMIT 1""",
            self.game_id,
            description[:50],
        )
        return dict(row) if row else None

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

    async def get_events_detailed(
        self, conn: Connection, from_cycle: int, limit: int = 5
    ) -> list[dict]:
        """Récupère les événements avec location et participants"""
        rows = await conn.fetch(
            """SELECT 
                ev.id, ev.type, ev.title, ev.description, 
                ev.planned_cycle, ev.time,
                loc.name as location_name,
                (SELECT array_agg(ent.name) 
                 FROM event_participants ep
                 JOIN entities ent ON ep.entity_id = ent.id
                 WHERE ep.event_id = ev.id) as participants
               FROM events ev
               LEFT JOIN entities loc ON ev.location_id = loc.id
               WHERE ev.game_id = $1 
                 AND ev.completed = false 
                 AND ev.cancelled = false
                 AND ev.planned_cycle >= $2
               ORDER BY ev.planned_cycle ASC
               LIMIT $3""",
            self.game_id,
            from_cycle,
            limit,
        )
        return [dict(r) for r in rows]
