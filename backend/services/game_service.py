"""
LDVELH - Game Service
Logique métier utilisant le schéma Knowledge Graph
"""

import json
from uuid import UUID
from typing import Optional
import asyncpg

from services.state_normalizer import (
    STATS_DEFAUT,
    normalize_game_state,
    game_state_to_dict,
)


class GameService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # CRUD PARTIES
    # =========================================================================

    async def list_games(self) -> list[dict]:
        """Liste toutes les parties actives"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT g.id, g.name, g.created_at, g.updated_at,
                       (SELECT MAX(cycle) FROM chat_messages WHERE game_id = g.id) as current_cycle,
                       (SELECT day FROM cycle_summaries WHERE game_id = g.id ORDER BY cycle DESC LIMIT 1) as jour
                FROM games g
                WHERE g.active = true
                ORDER BY g.updated_at DESC
            """)

        return [
            {
                "id": str(row["id"]),
                "nom": row["name"],
                "cycle_actuel": row["current_cycle"] or 0,
                "jour": row["jour"] or 1,
                "created_at": row["created_at"].isoformat()
                if row["created_at"]
                else None,
                "updated_at": row["updated_at"].isoformat()
                if row["updated_at"]
                else None,
            }
            for row in rows
        ]

    async def create_game(self) -> UUID:
        """Crée une nouvelle partie"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO games (name)
                VALUES ('Nouvelle partie')
                RETURNING id
            """)
        return row["id"]

    async def delete_game(self, game_id: UUID) -> None:
        """Supprime une partie (cascade sur toutes les tables liées)"""
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
    # LOAD GAME STATE
    # =========================================================================

    async def load_game_state(self, game_id: UUID) -> dict:
        """Charge l'état complet depuis le KG"""
        async with self.pool.acquire() as conn:
            # Vérifier que la partie existe
            game = await conn.fetchrow(
                "SELECT id, name, active FROM games WHERE id = $1", game_id
            )
            if not game:
                raise ValueError(f"Game {game_id} not found")

            # Récupérer le protagoniste et ses attributs
            protagonist = await conn.fetchrow(
                """
                SELECT e.id, e.name
                FROM entities e
                WHERE e.game_id = $1 AND e.type = 'protagonist' AND e.removed_cycle IS NULL
            """,
                game_id,
            )

            # Stats du protagoniste via attributes
            stats = {
                "energie": STATS_DEFAUT["energie"],
                "moral": STATS_DEFAUT["moral"],
                "sante": STATS_DEFAUT["sante"],
                "credits": STATS_DEFAUT["credits"],
            }

            if protagonist:
                attrs = await conn.fetch(
                    """
                    SELECT key, value FROM attributes
                    WHERE entity_id = $1 AND end_cycle IS NULL
                """,
                    protagonist["id"],
                )

                for attr in attrs:
                    if attr["key"] == "energy":
                        stats["energie"] = float(attr["value"])
                    elif attr["key"] == "morale":
                        stats["moral"] = float(attr["value"])
                    elif attr["key"] == "health":
                        stats["sante"] = float(attr["value"])
                    elif attr["key"] == "credits":
                        stats["credits"] = int(attr["value"])

            # Inventaire via la vue v_inventory
            inv_rows = await conn.fetch(
                """
                SELECT object_name, category, quantity, state, location, base_value
                FROM v_inventory
                WHERE game_id = $1
            """,
                game_id,
            )

            inventaire = [
                {
                    "nom": row["object_name"],
                    "categorie": row["category"],
                    "quantite": row["quantity"] or 1,
                    "etat": row["state"],
                    "localisation": row["location"],
                    "valeur_neuve": row["base_value"] or 0,
                }
                for row in inv_rows
            ]

            # IA compagnon
            ia_row = await conn.fetchrow(
                """
                SELECT e.name, ec.traits
                FROM entities e
                LEFT JOIN entity_ais ec ON ec.entity_id = e.id
                WHERE e.game_id = $1 AND e.type = 'ai' AND e.removed_cycle IS NULL
                LIMIT 1
            """,
                game_id,
            )

            # Dernier état de la partie (depuis le dernier message assistant)
            last_state = await conn.fetchrow(
                """
                SELECT cycle, state_snapshot
                FROM chat_messages
                WHERE game_id = $1 AND role = 'assistant' AND state_snapshot IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
            """,
                game_id,
            )

            # Infos du cycle depuis cycle_summaries
            cycle_info = await conn.fetchrow(
                """
                SELECT cycle, day, date, key_events
                FROM cycle_summaries
                WHERE game_id = $1
                ORDER BY cycle DESC
                LIMIT 1
            """,
                game_id,
            )

        # Construire les données brutes
        current_cycle = last_state["cycle"] if last_state else 0
        snapshot = (
            json.loads(last_state["state_snapshot"])
            if last_state and last_state["state_snapshot"]
            else {}
        )

        partie_data = {
            "id": game_id,
            "nom": game["name"],
            "cycle_actuel": current_cycle,
            "jour": cycle_info["day"] if cycle_info else 1,
            "date_jeu": cycle_info["date"] if cycle_info else None,
            "heure": snapshot.get("time", "08h00"),
            "lieu_actuel": snapshot.get("location"),
            "pnjs_presents": snapshot.get("npcs_present", []),
        }

        valentin_data = {
            **stats,
            "inventaire": inventaire,
        }

        ia_data = None
        if ia_row:
            ia_data = {
                "nom": ia_row["name"],
                "personnalite": ia_row["traits"],
            }

        # Normaliser avec Pydantic
        state = normalize_game_state(
            partie_data=partie_data,
            valentin_data=valentin_data,
            ia_data=ia_data,
        )

        return game_state_to_dict(state)

    async def load_chat_messages(self, game_id: UUID) -> list[dict]:
        """Charge les messages d'une partie"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content, cycle
                FROM chat_messages
                WHERE game_id = $1
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

    async def process_init(self, game_id: UUID, world_gen) -> dict:
        """Peuple le KG avec la génération du monde"""
        from kg.populator import KGPopulator

        populator = KGPopulator(self.pool, game_id)
        result = await populator.populate_world(world_gen)

        # Sauvegarder le résumé initial
        async with self.pool.acquire() as conn:
            arrival_event = {
                "type": "world_generation",
                "arrival_location": world_gen.arrival_event.location
                if world_gen.arrival_event
                else None,
            }
            await conn.execute(
                """
                INSERT INTO cycle_summaries (game_id, cycle, day, date, key_events)
                VALUES ($1, 1, 1, $2, $3)
                ON CONFLICT (game_id, cycle) DO UPDATE SET key_events = $3
            """,
                game_id,
                world_gen.starting_date
                if hasattr(world_gen, "starting_date")
                else None,
                json.dumps(arrival_event),
            )

        return result

    # =========================================================================
    # PROCESS LIGHT (Narration)
    # =========================================================================

    async def process_light(self, game_id: UUID, narration, current_cycle: int) -> dict:
        """Traite la sortie du narrateur"""
        new_cycle = current_cycle + 1
        time = narration.time or "08h00"
        location = narration.current_location
        npcs = narration.npcs_present or []

        # Gestion du changement de jour
        day_info = narration.day_transition
        new_day, new_date = None, None

        async with self.pool.acquire() as conn:
            # Récupérer le jour actuel
            current = await conn.fetchrow(
                """
                SELECT day, date FROM cycle_summaries
                WHERE game_id = $1 ORDER BY cycle DESC LIMIT 1
            """,
                game_id,
            )

            current_day = current["day"] if current else 1
            current_date = current["date"] if current else None

            if day_info:
                new_day = (
                    day_info.new_day
                    if hasattr(day_info, "new_day")
                    else current_day + 1
                )
                new_date = (
                    day_info.new_date if hasattr(day_info, "new_date") else current_date
                )

            # Appliquer les changements de stats via les fonctions SQL
            if narration.stats_changes:
                sc = narration.stats_changes
                if sc.energy:
                    await conn.execute(
                        "SELECT update_gauge($1, 'energy', $2, $3)",
                        game_id,
                        sc.energy,
                        new_cycle,
                    )
                if sc.morale:
                    await conn.execute(
                        "SELECT update_gauge($1, 'morale', $2, $3)",
                        game_id,
                        sc.morale,
                        new_cycle,
                    )
                if sc.health:
                    await conn.execute(
                        "SELECT update_gauge($1, 'health', $2, $3)",
                        game_id,
                        sc.health,
                        new_cycle,
                    )
                if sc.credits:
                    await conn.execute(
                        "SELECT credit_transaction($1, $2, $3, $4)",
                        game_id,
                        sc.credits,
                        new_cycle,
                        "Narration",
                    )

            # Mettre à jour cycle_summaries
            await conn.execute(
                """
                INSERT INTO cycle_summaries (game_id, cycle, day, date)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (game_id, cycle) DO UPDATE SET day = $3, date = $4
            """,
                game_id,
                new_cycle,
                new_day or current_day,
                new_date or current_date,
            )

            # Mettre à jour updated_at de la partie
            await conn.execute(
                "UPDATE games SET updated_at = NOW() WHERE id = $1", game_id
            )

        state_snapshot = {
            "cycle": new_cycle,
            "time": time,
            "location": location,
            "npcs_present": npcs,
        }

        return {
            "cycle": new_cycle,
            "time": time,
            "location": location,
            "npcs_present": npcs,
            "day": new_day or current_day,
            "date": new_date or current_date,
            "state_snapshot": state_snapshot,
        }

    # =========================================================================
    # BUILD NARRATION CONTEXT
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
        from kg.context_builder import ContextBuilder

        builder = ContextBuilder(self.pool, game_id)
        return await builder.build_context(
            player_input=player_input,
            current_cycle=current_cycle,
            current_time=current_time,
            current_location=current_location,
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
        state_snapshot: Optional[dict] = None,
    ) -> tuple[UUID, UUID]:
        """Sauvegarde les messages"""
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
        """Rollback en utilisant la fonction SQL"""
        async with self.pool.acquire() as conn:
            # Trouver le cycle correspondant à l'index
            messages = await conn.fetch(
                """
                SELECT cycle FROM chat_messages
                WHERE game_id = $1 ORDER BY created_at ASC
            """,
                game_id,
            )

            if from_index >= len(messages):
                return {"deleted": 0}

            target_cycle = messages[from_index]["cycle"] - 1 if from_index > 0 else 0

            # Utiliser la fonction de rollback du schéma
            result = await conn.fetchrow(
                "SELECT * FROM rollback_to_cycle($1, $2)", game_id, target_cycle
            )

        return {
            "deleted": len(messages) - from_index,
            "target_cycle": target_cycle,
            "rollback_result": dict(result) if result else {},
        }
