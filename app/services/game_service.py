"""
LDVELH - Game Service
Logique métier du jeu
"""

from uuid import UUID

import asyncpg
from kg.context_builder import ContextBuilder
from kg.specialized_populators import WorldPopulator
from schema import NarrationContext, NarrationOutput, WorldGeneration

from config import STATS_VALENTIN_DEFAUT
from kg.populator import KnowledgeGraphPopulator


class GameService:
    """Service principal pour la gestion du jeu"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # GESTION DES PARTIES
    # =========================================================================

    async def create_game(self, name: str = "Nouvelle partie") -> UUID:
        """Crée une nouvelle partie"""
        async with self.pool.acquire() as conn:
            game_id = await conn.fetchval(
                """INSERT INTO games (name, active) 
                   VALUES ($1, true) 
                   RETURNING id""",
                name,
            )
            return game_id

    async def list_games(self) -> list[dict]:
        """Liste les parties actives"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, name, created_at, updated_at
                   FROM games
                   WHERE active = true
                   ORDER BY updated_at DESC"""
            )
            return [dict(r) for r in rows]

    async def delete_game(self, game_id: UUID) -> bool:
        """Supprime une partie (soft delete)"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE games SET active = false WHERE id = $1", game_id)
            return True

    async def rename_game(self, game_id: UUID, new_name: str) -> bool:
        """Renomme une partie"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE games SET name = $1, updated_at = NOW() WHERE id = $2", new_name, game_id)
            return True

    # =========================================================================
    # CHARGEMENT ÉTAT
    # =========================================================================

    async def load_game_state(self, game_id: UUID) -> dict:
        """Charge l'état complet d'une partie"""
        async with self.pool.acquire() as conn:
            # Vérifier que la partie existe
            game = await conn.fetchrow("SELECT name, created_at FROM games WHERE id = $1 AND active = true", game_id)
            if not game:
                raise ValueError(f"Partie {game_id} non trouvée")

            # Récupérer le dernier cycle
            last_summary = await conn.fetchrow(
                """SELECT cycle, day, date, summary
                   FROM cycle_summaries
                   WHERE game_id = $1
                   ORDER BY cycle DESC
                   LIMIT 1""",
                game_id,
            )

            # Récupérer le dernier message pour l'état courant
            last_msg = await conn.fetchrow(
                """SELECT cycle, state_snapshot
                   FROM chat_messages
                   WHERE game_id = $1
                   ORDER BY created_at DESC
                   LIMIT 1""",
                game_id,
            )

            current_cycle = 1
            current_day = 1
            current_date = None
            current_time = "8h00"
            current_location = None
            npcs_present = []

            if last_msg and last_msg["state_snapshot"]:
                snapshot = last_msg["state_snapshot"]
                current_cycle = snapshot.get("cycle", 1)
                current_time = snapshot.get("time", "08h00")
                current_location = snapshot.get("location")
                npcs_present = snapshot.get("npcs_present", [])

            if last_summary:
                current_day = last_summary["day"] or current_cycle
                current_date = last_summary["date"]

            # Récupérer les stats du protagoniste
            protagonist_stats = await self._get_protagonist_stats(conn, game_id)

            # Récupérer l'inventaire
            inventory = await self._get_inventory(conn, game_id)

            # Récupérer l'IA
            ia_info = await self._get_ia_info(conn, game_id)

            # Vérifier si le monde est créé
            world_exists = await conn.fetchval(
                """SELECT EXISTS(
                    SELECT 1 FROM entities 
                    WHERE game_id = $1 AND type = 'protagonist'
                )""",
                game_id,
            )

            return {
                "partie": {
                    "cycle_actuel": current_cycle,
                    "jour": current_day,
                    "date_jeu": current_date,
                    "heure": current_time,
                    "lieu_actuel": current_location,
                    "pnjs_presents": npcs_present,
                    "nom": game["name"],
                },
                "valentin": {**protagonist_stats, "inventaire": inventory},
                "ia": ia_info,
                "monde_cree": world_exists,
            }

    async def load_chat_messages(self, game_id: UUID) -> list[dict]:
        """Charge les messages d'une partie"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT role, content, cycle, summary, created_at
                   FROM chat_messages
                   WHERE game_id = $1
                   ORDER BY created_at ASC""",
                game_id,
            )
            return [dict(r) for r in rows]

    # =========================================================================
    # TRAITEMENT INIT (World Builder)
    # =========================================================================

    async def process_init(self, game_id: UUID, world_gen: WorldGeneration) -> dict:
        """Traite la génération du monde initial"""
        populator = WorldPopulator(self.pool, game_id)

        async with self.pool.acquire() as conn:
            # Le WorldPopulator crée tout
            await populator.populate(world_gen)

            # Mettre à jour le nom de la partie
            await conn.execute(
                "UPDATE games SET name = $1, updated_at = NOW() WHERE id = $2", world_gen.world.name, game_id
            )

        return {
            "monde": world_gen.world.name,
            "ia_nom": world_gen.personal_ai.name,
            "lieu_depart": world_gen.arrival_event.arrival_location_ref,
            "credits": world_gen.protagonist.initial_credits,
        }

    # =========================================================================
    # TRAITEMENT LIGHT (Narration)
    # =========================================================================

    async def process_light(self, game_id: UUID, narration: NarrationOutput, current_cycle: int) -> dict:
        """Traite une réponse narrative"""
        async with self.pool.acquire() as conn:
            # Gérer la transition de jour
            new_cycle = current_cycle
            new_day = None
            new_date = None

            if narration.day_transition:
                new_cycle = narration.day_transition.new_cycle
                new_day = narration.day_transition.new_day
                new_date = narration.day_transition.new_date

                # Sauvegarder le résumé du cycle précédent
                await conn.execute(
                    """INSERT INTO cycle_summaries (game_id, cycle, day, date, summary)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (game_id, cycle) DO UPDATE SET
                         day = EXCLUDED.day,
                         date = EXCLUDED.date,
                         summary = EXCLUDED.summary""",
                    game_id,
                    current_cycle,
                    new_day - 1 if new_day else None,
                    None,
                    narration.day_transition.night_summary,
                )

            # Créer le snapshot d'état
            state_snapshot = {
                "cycle": new_cycle,
                "time": narration.time.new_time,
                "location": narration.current_location,
                "npcs_present": narration.npcs_present,
            }

            return {
                "cycle": new_cycle,
                "day": new_day,
                "date": new_date,
                "time": narration.time.new_time,
                "location": narration.current_location,
                "npcs_present": narration.npcs_present,
                "state_snapshot": state_snapshot,
            }

    # =========================================================================
    # SAUVEGARDE MESSAGES
    # =========================================================================

    async def save_messages(
        self,
        game_id: UUID,
        user_message: str,
        assistant_message: str,
        cycle: int,
        state_snapshot: dict,
        summary: str | None = None,
    ) -> None:
        """Sauvegarde les messages user et assistant"""
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO chat_messages 
                   (game_id, role, content, cycle, summary, state_snapshot)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                [
                    (game_id, "user", user_message, cycle, None, state_snapshot),
                    (game_id, "assistant", assistant_message, cycle, summary, None),
                ],
            )

            # Mettre à jour le timestamp de la partie
            await conn.execute("UPDATE games SET updated_at = NOW() WHERE id = $1", game_id)

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_message(self, game_id: UUID, message_index: int) -> dict:
        """Rollback à un message spécifique"""
        async with self.pool.acquire() as conn:
            # Récupérer tous les messages
            messages = await conn.fetch(
                """SELECT id, created_at, cycle, state_snapshot
                   FROM chat_messages
                   WHERE game_id = $1
                   ORDER BY created_at ASC""",
                game_id,
            )

            if message_index >= len(messages):
                return {"success": True, "deleted": 0}

            target_msg = messages[message_index]

            # Utiliser le populator pour le rollback
            populator = KnowledgeGraphPopulator(self.pool, game_id)
            await populator.load_registry(conn)

            stats = await populator.rollback_to_message(conn, target_msg["id"], include_message=False)

            return {"success": True, **stats}

    # =========================================================================
    # CONTEXT BUILDING
    # =========================================================================

    async def build_narration_context(
        self,
        game_id: UUID,
        player_input: str,
        current_cycle: int,
        current_time: str,
        current_location: str,
    ) -> NarrationContext:
        """Construit le contexte pour le narrateur"""
        async with self.pool.acquire() as conn:
            builder = ContextBuilder(game_id)
            return await builder.build(
                conn,
                player_input=player_input,
                current_cycle=current_cycle,
                current_time=current_time,
                current_location_name=current_location,
            )

    async def get_known_entities(self, game_id: UUID) -> list[str]:
        """Récupère les noms des entités connues"""
        async with self.pool.acquire() as conn:
            builder = ContextBuilder(game_id)
            return await builder.get_known_entity_names(conn)

    # =========================================================================
    # HELPERS PRIVÉS
    # =========================================================================

    async def _get_protagonist_stats(self, conn: asyncpg.Connection, game_id: UUID) -> dict:
        """Récupère les stats du protagoniste"""
        row = await conn.fetchrow(
            """SELECT e.id
               FROM entities e
               WHERE e.game_id = $1 
               AND e.type = 'protagonist'
               AND e.removed_cycle IS NULL""",
            game_id,
        )

        if not row:
            return STATS_VALENTIN_DEFAUT.copy()

        attrs = await conn.fetch(
            """SELECT key, value
               FROM attributes
               WHERE entity_id = $1 AND end_cycle IS NULL""",
            row["id"],
        )

        attr_dict = {a["key"]: a["value"] for a in attrs}

        return {
            "energie": float(attr_dict.get("energy", STATS_VALENTIN_DEFAUT["energie"])),
            "moral": float(attr_dict.get("morale", STATS_VALENTIN_DEFAUT["moral"])),
            "sante": float(attr_dict.get("health", STATS_VALENTIN_DEFAUT["sante"])),
            "credits": int(attr_dict.get("credits", STATS_VALENTIN_DEFAUT["credits"])),
        }

    async def _get_inventory(self, conn: asyncpg.Connection, game_id: UUID) -> list[dict]:
        """Récupère l'inventaire du protagoniste"""
        rows = await conn.fetch(
            """SELECT e2.id, e2.name, eo.category, ro.quantity,
                      a.value as emotional
               FROM entities e
               JOIN relations r ON r.source_id = e.id
               JOIN entities e2 ON e2.id = r.target_id
               JOIN entity_objects eo ON eo.entity_id = e2.id
               LEFT JOIN relations_ownership ro ON ro.relation_id = r.id
               LEFT JOIN attributes a ON a.entity_id = e2.id 
                   AND a.key = 'emotional_significance' AND a.end_cycle IS NULL
               WHERE e.game_id = $1 
               AND e.type = 'protagonist' 
               AND e.removed_cycle IS NULL
               AND r.type = 'owns' 
               AND r.end_cycle IS NULL
               AND e2.removed_cycle IS NULL""",
            game_id,
        )

        return [
            {
                "id": str(r["id"]),
                "nom": r["name"],
                "quantite": r["quantity"] or 1,
                "categorie": r["category"] or "autre",
                "emotionnel": bool(r["emotional"]),
            }
            for r in rows
        ]

    async def _get_ia_info(self, conn: asyncpg.Connection, game_id: UUID) -> dict | None:
        """Récupère les infos de l'IA personnelle"""
        row = await conn.fetchrow(
            """SELECT e.name, ea.traits
               FROM entities e
               JOIN entity_ais ea ON ea.entity_id = e.id
               WHERE e.game_id = $1 
               AND e.type = 'ai'
               AND e.removed_cycle IS NULL
               LIMIT 1""",
            game_id,
        )

        if not row:
            return None

        import json

        traits = json.loads(row["traits"]) if row["traits"] else {}

        return {"nom": row["name"], **traits}
