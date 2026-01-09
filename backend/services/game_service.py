"""
LDVELH - Game Service
Logique métier pour la gestion des parties
"""

from uuid import UUID
from typing import Optional
import asyncpg

from services.state_normalizer import (
    normalize_game_state,
    game_state_to_dict,
    STATS_DEFAUT,
)


class GameService:
    """Service pour la gestion des parties"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # =========================================================================
    # CRUD PARTIES
    # =========================================================================

    async def list_games(self) -> list[dict]:
        """Liste toutes les parties"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, status, current_cycle, narrative_day,
                       created_at, updated_at
                FROM games
                WHERE status = 'active'
                ORDER BY updated_at DESC
            """)

        return [
            {
                "id": str(row["id"]),
                "nom": row["name"],
                "cycle_actuel": row["current_cycle"],
                "jour": row["narrative_day"],
                "status": row["status"],
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
            row = await conn.fetchrow(
                """
                INSERT INTO games (name, current_cycle, energy, morale, health, credits)
                VALUES ('Nouvelle partie', 0, $1, $2, $3, $4)
                RETURNING id
            """,
                STATS_DEFAUT["energie"],
                STATS_DEFAUT["moral"],
                STATS_DEFAUT["sante"],
                STATS_DEFAUT["credits"],
            )

        return row["id"]

    async def delete_game(self, game_id: UUID) -> None:
        """Supprime une partie"""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM games WHERE id = $1", game_id)

    async def rename_game(self, game_id: UUID, name: str) -> None:
        """Renomme une partie"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE games SET name = $1 WHERE id = $2", name, game_id
            )

    # =========================================================================
    # LOAD GAME STATE (NORMALISÉ)
    # =========================================================================

    async def load_game_state(self, game_id: UUID) -> dict:
        """
        Charge l'état complet d'une partie.
        Retourne un état déjà normalisé pour le frontend.
        """
        async with self.pool.acquire() as conn:
            # Charger la partie
            game_row = await conn.fetchrow(
                """
                SELECT id, name, status, current_cycle, narrative_day,
                       universe_date, current_time, current_location, npcs_present,
                       energy, morale, health, credits,
                       created_at, updated_at
                FROM games
                WHERE id = $1
            """,
                game_id,
            )

            if not game_row:
                raise ValueError(f"Game {game_id} not found")

            # Charger l'inventaire
            inv_rows = await conn.fetch(
                """
                SELECT id, name, category, quantity, location, condition,
                       base_value, lent_to
                FROM inventory
                WHERE game_id = $1 AND removed_cycle IS NULL
                ORDER BY name
            """,
                game_id,
            )

            # Charger les messages
            msg_rows = await conn.fetch(
                """
                SELECT role, content, cycle, created_at
                FROM chat_messages
                WHERE game_id = $1
                ORDER BY created_at ASC
            """,
                game_id,
            )

            # Charger l'IA (si elle existe dans les entités)
            ia_row = await conn.fetchrow(
                """
                SELECT name, properties
                FROM entities
                WHERE game_id = $1 AND type = 'ia'
                LIMIT 1
            """,
                game_id,
            )

        # Construire les données brutes
        partie_data = {
            "id": game_row["id"],
            "nom": game_row["name"],
            "status": game_row["status"],
            "cycle_actuel": game_row["current_cycle"],
            "jour": game_row["narrative_day"],
            "date_jeu": game_row["universe_date"],
            "heure": game_row["current_time"],
            "lieu_actuel": game_row["current_location"],
            "pnjs_presents": game_row["npcs_present"] or [],
            "created_at": game_row["created_at"],
            "updated_at": game_row["updated_at"],
        }

        valentin_data = {
            "energie": game_row["energy"],
            "moral": game_row["morale"],
            "sante": game_row["health"],
            "credits": game_row["credits"],
            "inventaire": [
                {
                    "id": row["id"],
                    "nom": row["name"],
                    "categorie": row["category"],
                    "quantite": row["quantity"],
                    "localisation": row["location"],
                    "etat": row["condition"],
                    "valeur_neuve": row["base_value"],
                    "prete_a": row["lent_to"],
                }
                for row in inv_rows
            ],
        }

        ia_data = None
        if ia_row:
            props = ia_row["properties"] or {}
            ia_data = {
                "nom": ia_row["name"],
                "personnalite": props.get("personnalite"),
                "relation": props.get("relation"),
            }

        # Normaliser avec Pydantic
        state = normalize_game_state(
            partie_data=partie_data,
            valentin_data=valentin_data,
            ia_data=ia_data,
        )

        # Formater les messages
        messages = [
            {
                "role": row["role"],
                "content": row["content"],
                "cycle": row["cycle"],
            }
            for row in msg_rows
        ]

        return {
            "state": game_state_to_dict(state),
            "messages": messages,
            # Raccourcis pour compatibilité
            "partie": state.partie.model_dump() if state.partie else None,
            "valentin": state.valentin.model_dump(),
            "ia": state.ia.model_dump() if state.ia else None,
        }

    # =========================================================================
    # UPDATE GAME STATE
    # =========================================================================

    async def update_game_state(
        self,
        game_id: UUID,
        cycle: Optional[int] = None,
        day: Optional[int] = None,
        date: Optional[str] = None,
        time: Optional[str] = None,
        location: Optional[str] = None,
        npcs_present: Optional[list[str]] = None,
        energy: Optional[float] = None,
        morale: Optional[float] = None,
        health: Optional[float] = None,
        credits: Optional[int] = None,
    ) -> None:
        """Met à jour l'état d'une partie"""

        # Construire la query dynamiquement
        updates = []
        params = []
        param_idx = 1

        if cycle is not None:
            updates.append(f"current_cycle = ${param_idx}")
            params.append(cycle)
            param_idx += 1

        if day is not None:
            updates.append(f"narrative_day = ${param_idx}")
            params.append(day)
            param_idx += 1

        if date is not None:
            updates.append(f"universe_date = ${param_idx}")
            params.append(date)
            param_idx += 1

        if time is not None:
            updates.append(f"current_time = ${param_idx}")
            params.append(time)
            param_idx += 1

        if location is not None:
            updates.append(f"current_location = ${param_idx}")
            params.append(location)
            param_idx += 1

        if npcs_present is not None:
            updates.append(f"npcs_present = ${param_idx}")
            params.append(npcs_present)
            param_idx += 1

        if energy is not None:
            updates.append(f"energy = ${param_idx}")
            params.append(energy)
            param_idx += 1

        if morale is not None:
            updates.append(f"morale = ${param_idx}")
            params.append(morale)
            param_idx += 1

        if health is not None:
            updates.append(f"health = ${param_idx}")
            params.append(health)
            param_idx += 1

        if credits is not None:
            updates.append(f"credits = ${param_idx}")
            params.append(credits)
            param_idx += 1

        if not updates:
            return

        params.append(game_id)
        query = f"""
            UPDATE games
            SET {", ".join(updates)}, updated_at = NOW()
            WHERE id = ${param_idx}
        """

        async with self.pool.acquire() as conn:
            await conn.execute(query, *params)

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
        """Sauvegarde une paire de messages user/assistant"""

        async with self.pool.acquire() as conn:
            user_id = await conn.fetchval(
                """
                INSERT INTO chat_messages (game_id, role, content, cycle)
                VALUES ($1, 'user', $2, $3)
                RETURNING id
            """,
                game_id,
                user_message,
                cycle,
            )

            assistant_id = await conn.fetchval(
                """
                INSERT INTO chat_messages (game_id, role, content, cycle, state_snapshot)
                VALUES ($1, 'assistant', $2, $3, $4)
                RETURNING id
            """,
                game_id,
                assistant_message,
                cycle,
                state_snapshot,
            )

        return user_id, assistant_id

    # =========================================================================
    # PROCESS NARRATION (retourne état normalisé)
    # =========================================================================

    async def process_narration(
        self,
        game_id: UUID,
        narration_output: dict,
    ) -> dict:
        """
        Traite la sortie du narrateur et met à jour l'état.
        Retourne un état normalisé pour le frontend.
        """
        # Extraire les données de la narration
        time = narration_output.get("time") or narration_output.get("heure")
        location = narration_output.get("current_location") or narration_output.get(
            "lieu"
        )
        npcs = (
            narration_output.get("npcs_present")
            or narration_output.get("pnjs_presents")
            or []
        )

        day_transition = narration_output.get("day_transition")

        # Charger l'état actuel
        async with self.pool.acquire() as conn:
            current = await conn.fetchrow(
                "SELECT current_cycle, narrative_day, universe_date FROM games WHERE id = $1",
                game_id,
            )

        new_cycle = current["current_cycle"] + 1
        new_day = current["narrative_day"]
        new_date = current["universe_date"]

        if day_transition:
            new_day = day_transition.get("new_day", new_day + 1)
            new_date = day_transition.get("new_date", new_date)

        # Mettre à jour
        await self.update_game_state(
            game_id=game_id,
            cycle=new_cycle,
            day=new_day,
            date=new_date,
            time=time,
            location=location,
            npcs_present=npcs,
        )

        # Recharger et retourner l'état normalisé
        state = await self.load_game_state(game_id)

        return {
            "cycle": new_cycle,
            "time": time,
            "location": location,
            "npcs_present": npcs,
            "day": new_day if day_transition else None,
            "date": new_date if day_transition else None,
            "state": state["state"],
            "state_snapshot": {
                "cycle": new_cycle,
                "time": time,
                "location": location,
            },
        }

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_message(self, game_id: UUID, from_index: int) -> dict:
        """
        Rollback à un index de message spécifique.
        Supprime tous les messages après cet index.
        """
        async with self.pool.acquire() as conn:
            # Récupérer tous les messages ordonnés
            messages = await conn.fetch(
                """
                SELECT id, created_at
                FROM chat_messages
                WHERE game_id = $1
                ORDER BY created_at ASC
            """,
                game_id,
            )

            if from_index >= len(messages):
                return {"deleted": 0}

            # IDs à supprimer
            ids_to_delete = [m["id"] for m in messages[from_index:]]

            if ids_to_delete:
                await conn.execute(
                    """
                    DELETE FROM chat_messages
                    WHERE id = ANY($1)
                """,
                    ids_to_delete,
                )

        return {"deleted": len(ids_to_delete)}
