"""
LDVELH - Game Service
Logique métier pour la gestion des parties
"""

import json
from uuid import UUID

import asyncpg

from config import STATS_DEFAUT
from kg.specialized_populator import WorldPopulator
from schema import WorldGeneration, NarrationOutput
from services.state_normalizer import game_state_to_dict, normalize_game_state


class GameService:
    """Service principal pour la gestion des parties"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # CRUD PARTIES
    # =========================================================================

    async def list_games(self) -> list[dict]:
        """Liste toutes les parties actives"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    g.id, g.name, g.created_at, g.updated_at,
                    COALESCE(MAX(m.cycle), 0) AS current_cycle,
                    (SELECT day FROM cycle_summaries 
                     WHERE game_id = g.id ORDER BY cycle DESC LIMIT 1) AS jour
                FROM games g
                LEFT JOIN chat_messages m ON m.game_id = g.id
                WHERE g.active = true
                GROUP BY g.id
                ORDER BY g.updated_at DESC
            """)

        return [
            {
                "id": str(r["id"]),
                "nom": r["name"],
                "cycle_actuel": r["current_cycle"],
                "jour": r["jour"] or 1,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]

    async def create_game(self) -> UUID:
        """Crée une nouvelle partie"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO games (name) VALUES ('Nouvelle partie') RETURNING id"
            )

    async def delete_game(self, game_id: UUID) -> None:
        """Supprime une partie"""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM games WHERE id = $1", game_id)

    async def rename_game(self, game_id: UUID, name: str) -> None:
        """Renomme une partie"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE games SET name = $1, updated_at = NOW() WHERE id = $2",
                name,
                game_id,
            )

    # =========================================================================
    # CHARGEMENT ÉTAT
    # =========================================================================

    async def load_game_state(self, game_id: UUID) -> dict:
        """Charge l'état complet d'une partie"""
        async with self.pool.acquire() as conn:
            # Vérifier existence
            game = await conn.fetchrow(
                "SELECT id, name FROM games WHERE id = $1 AND active = true", game_id
            )
            if not game:
                raise ValueError(f"Partie {game_id} introuvable")

            # Vérifier si le monde est créé (protagoniste existe)
            monde_cree = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM entities 
                    WHERE game_id = $1 AND type = 'protagonist' AND removed_cycle IS NULL
                )
            """,
                game_id,
            )

            # Charger en parallèle
            stats = await self._load_protagonist_stats(conn, game_id)
            inventaire = await self._load_inventory(conn, game_id)
            ia = await self._load_ai_companion(conn, game_id)
            cycle_info = await self._load_cycle_info(conn, game_id)

        # Construire l'état
        partie = {
            "id": game_id,
            "nom": game["name"],
            "cycle_actuel": cycle_info["cycle"],
            "jour": cycle_info["day"],
            "date_jeu": cycle_info["date"],
            "heure": cycle_info["time"],
            "lieu_actuel": cycle_info["location"],
            "pnjs_presents": cycle_info["npcs_present"],
        }

        valentin = {**stats, "inventaire": inventaire}

        # Normaliser avec Pydantic
        state = normalize_game_state(
            partie_data=partie,
            valentin_data=valentin,
            ia_data=ia,
        )

        result = game_state_to_dict(state)
        result["monde_cree"] = monde_cree  # ← Ajouter le flag
        return result

    async def load_world_info(self, game_id: UUID) -> dict | None:
        """
        Reconstruit les infos de présentation du monde depuis le KG.
        Utilisé pour réafficher l'écran WorldReady après rechargement.
        """
        async with self.pool.acquire() as conn:
            # Vérifier si le monde existe
            monde_cree = await conn.fetchval(
                """SELECT EXISTS(
                    SELECT 1 FROM entities 
                    WHERE game_id = $1 AND type = 'protagonist' AND removed_cycle IS NULL
                )""",
                game_id,
            )

            if not monde_cree:
                return None

            # Récupérer le monde/station (seule entité location avec attribut 'population')
            world_row = await conn.fetchrow(
                """
                SELECT 
                    e.name,
                    el.location_type,
                    MAX(CASE WHEN a.key = 'atmosphere' THEN a.value END) as atmosphere,
                    MAX(CASE WHEN a.key = 'population' THEN a.value END) as population
                FROM entities e
                JOIN entity_locations el ON el.entity_id = e.id
                JOIN attributes a ON a.entity_id = e.id AND a.end_cycle IS NULL
                WHERE e.game_id = $1 
                  AND e.type = 'location' 
                  AND e.removed_cycle IS NULL
                  AND EXISTS (
                      SELECT 1 FROM attributes 
                      WHERE entity_id = e.id AND key = 'population' AND end_cycle IS NULL
                  )
                GROUP BY e.id, e.name, el.location_type
                LIMIT 1
                """,
                game_id,
            )

            # Compter les entités
            counts = await conn.fetchrow(
                """
                SELECT 
                    COUNT(*) FILTER (WHERE type = 'character') as nb_personnages,
                    COUNT(*) FILTER (WHERE type = 'location') as nb_lieux,
                    COUNT(*) FILTER (WHERE type = 'organization') as nb_organisations
                FROM entities
                WHERE game_id = $1 AND removed_cycle IS NULL
                """,
                game_id,
            )

            # Récupérer l'IA (traits est un JSON contenant voice, personality, quirk)
            ia_row = await conn.fetchrow(
                """
                SELECT e.name, ea.traits
                FROM entities e
                JOIN entity_ais ea ON ea.entity_id = e.id
                WHERE e.game_id = $1 AND e.type = 'ai' AND e.removed_cycle IS NULL
                LIMIT 1
                """,
                game_id,
            )

            # Récupérer le protagoniste avec ses crédits
            protag_row = await conn.fetchrow(
                """
                SELECT e.name, a.value as credits
                FROM entities e
                LEFT JOIN attributes a ON a.entity_id = e.id 
                    AND a.key = 'credits' AND a.end_cycle IS NULL
                WHERE e.game_id = $1 AND e.type = 'protagonist' AND e.removed_cycle IS NULL
                LIMIT 1
                """,
                game_id,
            )

            # Récupérer l'événement d'arrivée depuis cycle_summaries
            arrival_row = await conn.fetchrow(
                """SELECT key_events, day, date FROM cycle_summaries 
                   WHERE game_id = $1 AND cycle = 1""",
                game_id,
            )

            # Construire le résultat
            monde = None
            if world_row:
                population = world_row["population"]
                if population and isinstance(population, str):
                    try:
                        population = int(population)
                    except ValueError:
                        population = None
                monde = {
                    "nom": world_row["name"],
                    "type": world_row["location_type"],
                    "atmosphere": world_row["atmosphere"],
                    "population": population,
                }

            ia = None
            if ia_row:
                # traits est un JSON: {"voice": "...", "personality": [...], "quirk": "..."}
                traits_data = ia_row["traits"]
                if traits_data and isinstance(traits_data, str):
                    try:
                        traits_data = json.loads(traits_data)
                    except json.JSONDecodeError:
                        traits_data = {}
                elif not traits_data:
                    traits_data = {}

                ia = {
                    "nom": ia_row["name"],
                    "personnalite": traits_data.get("personality", []),
                    "quirk": traits_data.get("quirk"),
                }

            protagoniste = None
            if protag_row:
                credits = protag_row["credits"]
                if credits:
                    try:
                        credits = int(credits)
                    except (ValueError, TypeError):
                        credits = 0
                protagoniste = {
                    "nom": protag_row["name"],
                    "credits": credits or 0,
                }

            arrivee = None
            if arrival_row and arrival_row["key_events"]:
                events = (
                    json.loads(arrival_row["key_events"])
                    if isinstance(arrival_row["key_events"], str)
                    else arrival_row["key_events"]
                )
                date_str = arrival_row["date"]
                if arrival_row["day"] and date_str:
                    date_str = f"{arrival_row['day']} {date_str}"
                arrivee = {
                    "lieu": events.get("arrival_location"),
                    "date": date_str,
                    "heure": events.get("hour"),
                    "ambiance": events.get("initial_mood"),
                }

            return {
                "monde_cree": True,
                "monde": monde,
                "ia": ia,
                "protagoniste": protagoniste,
                "nb_personnages": counts["nb_personnages"] if counts else 0,
                "nb_lieux": counts["nb_lieux"] if counts else 0,
                "nb_organisations": counts["nb_organisations"] if counts else 0,
                "arrivee": arrivee,
            }

    async def _load_protagonist_stats(self, conn, game_id: UUID) -> dict:
        """Charge les stats du protagoniste via la vue v_current_attributes"""
        rows = await conn.fetch(
            """
            SELECT key, value 
            FROM v_current_attributes
            WHERE game_id = $1 AND entity_type = 'protagonist'
              AND key IN ('energy', 'morale', 'health', 'credits')
        """,
            game_id,
        )

        stats = dict(STATS_DEFAUT)  # Copie des valeurs par défaut
        key_mapping = {
            "energy": "energie",
            "morale": "moral",
            "health": "sante",
            "credits": "credits",
        }

        for row in rows:
            if row["key"] in key_mapping:
                fr_key = key_mapping[row["key"]]
                stats[fr_key] = (
                    float(row["value"]) if fr_key != "credits" else int(row["value"])
                )

        return stats

    async def _load_inventory(self, conn, game_id: UUID) -> list[dict]:
        """Charge l'inventaire via la vue v_inventory"""
        rows = await conn.fetch(
            """
            SELECT object_name, category, quantity, state, location, base_value
            FROM v_inventory WHERE game_id = $1
        """,
            game_id,
        )

        return [
            {
                "nom": r["object_name"],
                "categorie": r["category"],
                "quantite": r["quantity"] or 1,
                "etat": r["state"],
                "localisation": r["location"],
                "valeur_neuve": r["base_value"] or 0,
            }
            for r in rows
        ]

    async def _load_ai_companion(self, conn, game_id: UUID) -> dict | None:
        """Charge l'IA compagnon"""
        row = await conn.fetchrow(
            """
            SELECT e.name, ea.traits
            FROM entities e
            LEFT JOIN entity_ais ea ON ea.entity_id = e.id
            WHERE e.game_id = $1 AND e.type = 'ai' AND e.removed_cycle IS NULL
            LIMIT 1
        """,
            game_id,
        )

        if not row:
            return None
        return {"nom": row["name"], "personnalite": row["traits"]}

    async def _load_cycle_info(self, conn, game_id: UUID) -> dict:
        """Charge les infos du cycle actuel depuis le dernier message assistant"""
        row = await conn.fetchrow(
            """
            SELECT m.cycle, m.day, m.date, m.time, 
                   e.name as location_name, m.npcs_present
            FROM chat_messages m
            LEFT JOIN entities e ON e.id = m.location_id
            WHERE m.game_id = $1 AND m.role = 'assistant'
            ORDER BY m.created_at DESC LIMIT 1
            """,
            game_id,
        )

        # Si on a un message, utiliser son état
        if row:
            npc_names = []
            if row["npcs_present"]:
                npc_rows = await conn.fetch(
                    """SELECT name FROM entities WHERE id = ANY($1)""",
                    row["npcs_present"],
                )
                npc_names = [r["name"] for r in npc_rows]

            day = row["day"] or "Lundi"
            date = row["date"]
            if day and date and date.startswith(day):
                date = date[len(day) :].strip()

            return {
                "cycle": row["cycle"],
                "day": row["day"] or "Lundi",
                "date": row["date"],
                "time": row["time"] or "08h00",
                "location": row["location_name"],
                "npcs_present": npc_names,
            }

        # Sinon, fallback sur les infos d'arrivée (first_light)
        arrival_row = await conn.fetchrow(
            """SELECT day, date, key_events FROM cycle_summaries 
               WHERE game_id = $1 AND cycle = 1""",
            game_id,
        )

        if arrival_row and arrival_row["key_events"]:
            day = arrival_row["day"] or "Lundi"
            date = arrival_row["date"]
            if day and date and date.startswith(day):
                date = date[len(day) :].strip()

            events = (
                json.loads(arrival_row["key_events"])
                if isinstance(arrival_row["key_events"], str)
                else arrival_row["key_events"]
            )

            return {
                "cycle": 1,
                "day": arrival_row["day"] or "Lundi",
                "date": arrival_row["date"],
                "time": events.get("hour", "08h00"),
                "location": events.get("arrival_location"),
                "npcs_present": [events["first_npc_encountered"]]
                if events.get("first_npc_encountered")
                else [],
            }

        # Fallback total (monde pas encore créé)
        return {
            "cycle": 0,
            "day": "Lundi",
            "date": None,
            "time": "08h00",
            "location": None,
            "npcs_present": [],
        }

    async def load_chat_messages(self, game_id: UUID) -> list[dict]:
        """Charge l'historique des messages"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content, cycle
                FROM chat_messages WHERE game_id = $1
                ORDER BY created_at ASC
            """,
                game_id,
            )

        return [
            {"role": r["role"], "content": r["content"], "cycle": r["cycle"]}
            for r in rows
        ]

    # =========================================================================
    # PROCESS INIT (World Generation)
    # =========================================================================

    async def process_init(self, game_id: UUID, world_gen: WorldGeneration) -> dict:
        """Peuple le Knowledge Graph avec la génération du monde"""
        populator = WorldPopulator(self.pool, game_id)
        await populator.populate(world_gen)

        arrival = world_gen.arrival_event

        return {
            "monde": {
                "nom": world_gen.world.name,
                "type": world_gen.world.station_type,
                "atmosphere": world_gen.world.atmosphere,
                "population": world_gen.world.population,
                "secteurs": world_gen.world.sectors,
            },
            "protagoniste": {
                "nom": world_gen.protagonist.name,
                "origine": world_gen.protagonist.origin_location,
                "raison_depart": world_gen.protagonist.departure_reason.value,
                "credits": world_gen.protagonist.initial_credits,
            },
            "ia": {
                "nom": world_gen.personal_ai.name,
                "personnalite": world_gen.personal_ai.personality_traits,
                "quirk": world_gen.personal_ai.quirk,
            },
            "nb_personnages": len(world_gen.characters),
            "nb_lieux": len(world_gen.locations),
            "nb_organisations": len(world_gen.organizations),
            "inventaire_count": len(world_gen.inventory),
            "arrivee": {
                "lieu": arrival.arrival_location_ref,
                "date": arrival.arrival_date,
                "heure": arrival.time,
                "ambiance": arrival.initial_mood,
                "besoin_immediat": arrival.immediate_need,
            }
            if arrival
            else None,
        }

    async def get_arrival_info(self, game_id: UUID) -> dict | None:
        """Récupère les infos d'arrivée initiales (cycle 1)"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT key_events FROM cycle_summaries 
                   WHERE game_id = $1 AND cycle = 1""",
                game_id,
            )

        if row and row["key_events"]:
            events = (
                json.loads(row["key_events"])
                if isinstance(row["key_events"], str)
                else row["key_events"]
            )
            return events
        return None

    # =========================================================================
    # PROCESS LIGHT (Narration)
    # =========================================================================

    async def process_light(
        self, game_id: UUID, narration: NarrationOutput, current_cycle: int
    ) -> dict:
        """Traite la sortie du narrateur et met à jour le cycle"""
        new_cycle = current_cycle + 1 if narration.day_transition else current_cycle
        new_time = narration.time.new_time if narration.time else ""
        location = narration.current_location
        npcs = narration.npcs_present or []

        async with self.pool.acquire() as conn:
            # Récupérer le jour/date actuels
            current = await conn.fetchrow(
                """
                SELECT day, date FROM cycle_summaries
                WHERE game_id = $1 ORDER BY cycle DESC LIMIT 1
            """,
                game_id,
            )

            current_day = current["day"] if current else "Lundi"
            current_date = current["date"] if current else None

            # Gérer le changement de jour si présent
            new_day, new_date = current_day, current_date
            if narration.day_transition:
                dt = narration.day_transition
                new_day = getattr(dt, "new_day", None)  # "Mardi" par exemple
                new_date = getattr(dt, "new_date", None)  # "15 Mars 2847"

            # Mettre à jour cycle_summaries
            await conn.execute(
                """
                INSERT INTO cycle_summaries (game_id, cycle, day, date)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (game_id, cycle) DO UPDATE SET day = $3, date = $4
            """,
                game_id,
                new_cycle,
                new_day,
                new_date,
            )

            # Mettre à jour timestamp de la partie
            await conn.execute(
                "UPDATE games SET updated_at = NOW() WHERE id = $1", game_id
            )

        state_snapshot = {
            "cycle": new_cycle,
            "time": new_time,
            "location": location,
            "npcs_present": npcs,
        }

        return {
            "cycle": new_cycle,
            "time": new_time,
            "location": location,
            "npcs_present": npcs,
            "day": new_day,
            "date": new_date,
            "state_snapshot": state_snapshot,
        }

    # =========================================================================
    # MESSAGES
    # =========================================================================

    async def save_messages(
        self,
        game_id: UUID,
        user_message: str,
        assistant_message: str,
        cycle: int,
        day: str | None = None,
        date: str | None = None,
        time: str | None = None,
        location_ref: str | None = None,
        npcs_present_refs: list[str] | None = None,
        summary: str | None = None,
    ) -> tuple[UUID, UUID]:
        """Sauvegarde une paire de messages (user + assistant)"""
        async with self.pool.acquire() as conn:
            # Résoudre location_ref → UUID
            location_id = None
            if location_ref:
                location_id = await conn.fetchval(
                    """SELECT id FROM entities 
                       WHERE game_id = $1 AND LOWER(name) = LOWER($2) AND removed_cycle IS NULL""",
                    game_id,
                    location_ref,
                )

            # Résoudre npcs_present_refs → UUID[]
            npc_ids = []
            if npcs_present_refs:
                rows = await conn.fetch(
                    """SELECT id FROM entities 
                       WHERE game_id = $1 AND LOWER(name) = ANY($2) AND removed_cycle IS NULL""",
                    game_id,
                    [n.lower() for n in npcs_present_refs],
                )
                npc_ids = [r["id"] for r in rows]

            user_id = await conn.fetchval(
                """INSERT INTO chat_messages (game_id, role, content, cycle)
                   VALUES ($1, 'user', $2, $3) RETURNING id""",
                game_id,
                user_message,
                cycle,
            )

            assistant_id = await conn.fetchval(
                """INSERT INTO chat_messages 
                   (game_id, role, content, cycle, day, date, time, location_id, npcs_present, summary)
                   VALUES ($1, 'assistant', $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
                game_id,
                assistant_message,
                cycle,
                day,
                date,
                time,
                location_id,
                npc_ids,
                summary,
            )

        return user_id, assistant_id

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_message(self, game_id: UUID, keep_until_index: int) -> dict:
        """
        Rollback: supprime tous les messages à partir de keep_until_index (inclus).

        Exemple: messages = [user0, assistant0, user1, assistant1]
        - keep_until_index=2 → garde [user0, assistant0], supprime [user1, assistant1]
        - keep_until_index=0 → supprime tout

        Args:
            game_id: ID de la partie
            keep_until_index: Index à partir duquel supprimer (inclus)

        Returns:
            dict avec deleted, target_cycle, rollback_result
        """
        async with self.pool.acquire() as conn:
            # Récupérer tous les messages ordonnés
            messages = await conn.fetch(
                """
                SELECT id, cycle, created_at FROM chat_messages
                WHERE game_id = $1 ORDER BY created_at ASC
                """,
                game_id,
            )

            if keep_until_index >= len(messages):
                # Rien à supprimer
                return {"deleted": 0, "target_cycle": None, "rollback_result": {}}

            # Messages à supprimer
            messages_to_delete = messages[keep_until_index:]

            if not messages_to_delete:
                return {"deleted": 0, "target_cycle": None, "rollback_result": {}}

            # Trouver le cycle cible (dernier cycle à GARDER)
            if keep_until_index > 0:
                target_cycle = messages[keep_until_index - 1]["cycle"]
            else:
                target_cycle = 0

            # 1. Supprimer les messages concernés
            ids_to_delete = [m["id"] for m in messages_to_delete]
            await conn.execute(
                "DELETE FROM chat_messages WHERE id = ANY($1)",
                ids_to_delete,
            )

            # 2. Rollback du KG (facts, relations, attributes, etc.)
            result = await conn.fetchrow(
                "SELECT * FROM rollback_to_cycle($1, $2)", game_id, target_cycle
            )

            # 3. Mettre à jour le timestamp de la partie
            await conn.execute(
                "UPDATE games SET updated_at = NOW() WHERE id = $1", game_id
            )

        return {
            "deleted": len(messages_to_delete),
            "target_cycle": target_cycle,
            "rollback_result": dict(result) if result else {},
        }
