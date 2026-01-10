"""
LDVELH - Game Service
Logique métier pour la gestion des parties
"""

import json
from uuid import UUID

import asyncpg

from config import STATS_DEFAUT
from kg.context_builder import ContextBuilder
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
        """Charge les infos du cycle actuel"""
        # Dernier snapshot depuis les messages
        snapshot_row = await conn.fetchrow(
            """
            SELECT cycle, state_snapshot
            FROM chat_messages
            WHERE game_id = $1 AND role = 'assistant' AND state_snapshot IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
        """,
            game_id,
        )

        # Infos du cycle depuis cycle_summaries
        summary_row = await conn.fetchrow(
            """
            SELECT cycle, day, date FROM cycle_summaries
            WHERE game_id = $1 ORDER BY cycle DESC LIMIT 1
        """,
            game_id,
        )

        snapshot = {}
        if snapshot_row and snapshot_row["state_snapshot"]:
            snapshot = json.loads(snapshot_row["state_snapshot"])

        return {
            "cycle": snapshot_row["cycle"] if snapshot_row else 0,
            "day": summary_row["day"] if summary_row else "Lundi",
            "date": summary_row["date"] if summary_row else None,
            "time": snapshot.get("time", "08h00"),
            "location": snapshot.get("location"),
            "npcs_present": snapshot.get("npcs_present", []),
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
        # Peupler via le WorldPopulator
        populator = WorldPopulator(self.pool, game_id)
        await populator.populate(world_gen)

        arrival = world_gen.arrival_event
        return {
            "monde_nom": world_gen.world.name,
            "monde_type": world_gen.world.station_type,
            "ia_nom": world_gen.personal_ai.name,
            "lieu_depart": arrival.arrival_location_ref if arrival else None,
        }

    # =========================================================================
    # PROCESS LIGHT (Narration)
    # =========================================================================

    async def process_light(
        self, game_id: UUID, narration: NarrationOutput, current_cycle: int
    ) -> dict:
        """Traite la sortie du narrateur et met à jour le cycle"""
        new_cycle = current_cycle + 1
        new_time = narration.time.new_time if narration.time else "08h00"
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
    # CONTEXTE NARRATION
    # =========================================================================

    async def build_narration_context(
        self,
        game_id: UUID,
        player_input: str,
        current_cycle: int,
        current_time: str,
        current_location: str,
    ) -> dict:
        """Construit le contexte pour le narrateur depuis le KG"""
        async with self.pool.acquire() as conn:
            builder = ContextBuilder(self.pool, game_id)
            return await builder.build(
                conn=conn,
                player_input=player_input,
                current_cycle=current_cycle,
                current_time=current_time,
                current_location_name=current_location,
            )

    # =========================================================================
    # MESSAGES
    # =========================================================================

    async def save_messages(
        self,
        game_id: UUID,
        user_message: str,
        assistant_message: str,
        cycle: int,
        state_snapshot: dict | None = None,
    ) -> tuple[UUID, UUID]:
        """Sauvegarde une paire de messages (user + assistant)"""
        async with self.pool.acquire() as conn:
            user_id = await conn.fetchval(
                """
                INSERT INTO chat_messages (game_id, role, content, cycle)
                VALUES ($1, 'user', $2, $3) RETURNING id
            """,
                game_id,
                user_message,
                cycle,
            )

            assistant_id = await conn.fetchval(
                """
                INSERT INTO chat_messages (game_id, role, content, cycle, state_snapshot)
                VALUES ($1, 'assistant', $2, $3, $4) RETURNING id
            """,
                game_id,
                assistant_message,
                cycle,
                json.dumps(state_snapshot) if state_snapshot else None,
            )

        return user_id, assistant_id

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_message(self, game_id: UUID, from_index: int) -> dict:
        """Rollback à un message spécifique via la fonction SQL"""
        async with self.pool.acquire() as conn:
            # Trouver le cycle cible
            cycles = await conn.fetch(
                """
                SELECT cycle FROM chat_messages
                WHERE game_id = $1 ORDER BY created_at ASC
            """,
                game_id,
            )

            if from_index >= len(cycles):
                return {"deleted": 0}

            target_cycle = cycles[from_index]["cycle"] - 1 if from_index > 0 else 0

            # Utiliser la fonction SQL de rollback
            result = await conn.fetchrow(
                "SELECT * FROM rollback_to_cycle($1, $2)", game_id, target_cycle
            )

        return {
            "deleted": len(cycles) - from_index,
            "target_cycle": target_cycle,
            "rollback_result": dict(result) if result else {},
        }
