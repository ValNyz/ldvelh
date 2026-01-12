"""
LDVELH - Game Service
Logique métier pour la gestion des parties
Utilise kg/reader.py et kg/populator.py pour l'accès BDD
"""

import json
from uuid import UUID

import asyncpg

from config import STATS_DEFAUT
from kg.reader import KnowledgeGraphReader
from kg.populator import KnowledgeGraphPopulator
from kg.specialized_populator import WorldPopulator
from schema import WorldGeneration, NarrationOutput


class GameService:
    """Service principal pour la gestion des parties"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    def _get_reader(self, game_id: UUID) -> KnowledgeGraphReader:
        """Crée un reader pour une partie"""
        return KnowledgeGraphReader(self.pool, game_id)

    def _get_populator(self, game_id: UUID) -> KnowledgeGraphPopulator:
        """Crée un populator pour une partie"""
        return KnowledgeGraphPopulator(self.pool, game_id)

    # =========================================================================
    # CRUD PARTIES
    # =========================================================================

    async def list_games(self) -> list[dict]:
        """Liste toutes les parties actives"""
        reader = KnowledgeGraphReader(self.pool)
        async with self.pool.acquire() as conn:
            games = await reader.list_games(conn, active_only=True)

        return [
            {
                "id": str(g["id"]),
                "nom": g["name"],
                "cycle_actuel": g["current_cycle"],
                "jour": g["current_date"] or 1,
                "created_at": g["created_at"].isoformat() if g["created_at"] else None,
                "updated_at": g["updated_at"].isoformat() if g["updated_at"] else None,
            }
            for g in games
        ]

    async def create_game(self) -> UUID:
        """Crée une nouvelle partie"""
        populator = KnowledgeGraphPopulator(self.pool)
        async with self.pool.acquire() as conn:
            return await populator.create_game(conn, "Nouvelle partie")

    async def delete_game(self, game_id: UUID) -> None:
        """Supprime une partie"""
        populator = self._get_populator(game_id)
        async with self.pool.acquire() as conn:
            await populator.delete_game(conn)

    async def rename_game(self, game_id: UUID, name: str) -> None:
        """Renomme une partie"""
        populator = self._get_populator(game_id)
        async with self.pool.acquire() as conn:
            await populator.rename_game(conn, name)

    # =========================================================================
    # CHARGEMENT ÉTAT
    # =========================================================================

    async def load_game_state(self, game_id: UUID) -> dict:
        """Charge l'état complet d'une partie"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            # Vérifier existence
            game = await reader.get_game(conn)
            if not game or not game["active"]:
                raise ValueError(f"Partie {game_id} introuvable")

            # Vérifier si le monde est créé
            monde_cree = await reader.is_world_created(conn)

            # Charger les données
            stats = await self._load_protagonist_stats(reader, conn)
            inventaire = await self._load_inventory(reader, conn)
            ia = await self._load_ai_companion(reader, conn)
            cycle_info = await self._load_cycle_info(reader, conn)

        # Construire l'état
        partie = {
            "id": game_id,
            "nom": game["name"],
            "cycle_actuel": cycle_info["cycle"],
            "date_jeu": cycle_info["date"],
            "heure": cycle_info["time"],
            "lieu_actuel": cycle_info["location"],
            "pnjs_presents": cycle_info["npcs_present"],
        }

        valentin = {**stats, "inventaire": inventaire}

        # Normaliser avec Pydantic
        from services.state_normalizer import game_state_to_dict, normalize_game_state

        state = normalize_game_state(
            partie_data=partie,
            valentin_data=valentin,
            ia_data=ia,
        )

        result = game_state_to_dict(state)
        result["monde_cree"] = monde_cree
        return result

    async def _load_protagonist_stats(self, reader: KnowledgeGraphReader, conn) -> dict:
        """Charge les stats du protagoniste"""
        row = await reader.get_protagonist_stats(conn)

        stats = dict(STATS_DEFAUT)
        if row:
            stats["energie"] = (
                float(row["energy"]) if row["energy"] else stats["energie"]
            )
            stats["moral"] = float(row["morale"]) if row["morale"] else stats["moral"]
            stats["sante"] = float(row["health"]) if row["health"] else stats["sante"]
            stats["credits"] = (
                int(row["credits"]) if row["credits"] else stats["credits"]
            )

        return stats

    async def _load_inventory(self, reader: KnowledgeGraphReader, conn) -> list[dict]:
        """Charge l'inventaire"""
        rows = await reader.get_inventory(conn)

        return [
            {
                "nom": r["object_name"],
                "categorie": r["category"] or "misc",
                "quantite": r["quantity"] or 1,
                "etat": r["condition"],
                "valeur_neuve": r["base_value"] or 0,
            }
            for r in rows
        ]

    async def _load_ai_companion(
        self, reader: KnowledgeGraphReader, conn
    ) -> dict | None:
        """Charge l'IA compagnon"""
        row = await reader.get_ai_companion(conn)
        if not row:
            return None

        # Parser traits depuis JSON
        traits = []
        if row["traits"]:
            try:
                traits = (
                    json.loads(row["traits"])
                    if isinstance(row["traits"], str)
                    else row["traits"]
                )
            except (json.JSONDecodeError, TypeError):
                traits = []

        return {
            "nom": row["name"],
            "personnalite": traits if isinstance(traits, list) else [],
            "voix": row["voice"],
            "quirk": row["quirk"],
        }

    async def _load_cycle_info(self, reader: KnowledgeGraphReader, conn) -> dict:
        """Charge les infos du cycle actuel"""
        # Récupérer le dernier message assistant
        last_msg = await reader.get_last_assistant_message(conn)

        if last_msg:
            # Récupérer les noms des NPCs présents
            npc_names = []
            if last_msg["npcs_present"]:
                npc_names = await reader.get_entity_names_by_ids(
                    conn, last_msg["npcs_present"]
                )

            return {
                "cycle": last_msg["cycle"],
                "date": last_msg["date"],
                "time": last_msg["time"] or "08h00",
                "location": last_msg["location_name"],
                "npcs_present": npc_names,
            }

        # Fallback sur les infos d'arrivée
        arrival = await reader.get_arrival_event(conn)
        if arrival and arrival["events"]:
            events = arrival["events"]
            return {
                "cycle": 1,
                "date": arrival["date"],
                "time": events.get("hour", "08h00"),
                "location": events.get("arrival_location"),
                "npcs_present": [events["first_npc_encountered"]]
                if events.get("first_npc_encountered")
                else [],
            }

        # Fallback total (monde pas encore créé)
        return {
            "cycle": 1,
            "date": "Lundi 1er janvier 2475",
            "time": "08h00",
            "location": None,
            "npcs_present": [],
        }

    async def load_world_info(self, game_id: UUID) -> dict | None:
        """Reconstruit les infos de présentation du monde depuis le KG."""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            # Vérifier si le monde existe
            if not await reader.is_world_created(conn):
                return None

            # Récupérer le monde/station (location racine)
            world_row = await reader.get_root_location(conn)

            # Compter les entités
            counts = await reader.get_entity_counts_by_type(conn)

            # Récupérer l'IA
            ia_row = await reader.get_ai_companion(conn)

            # Récupérer le protagoniste
            protag_row = await reader.get_protagonist(conn)

            # Récupérer l'événement d'arrivée
            arrival = await reader.get_arrival_event(conn)

        # Construire le résultat
        monde = None
        if world_row:
            sectors = None
            if world_row["notable_features"]:
                try:
                    sectors = json.loads(world_row["notable_features"])
                except (json.JSONDecodeError, TypeError):
                    sectors = None

            monde = {
                "nom": world_row["name"],
                "type": world_row["location_type"],
                "atmosphere": world_row["atmosphere"],
                "secteurs": sectors,
            }

        ia = None
        if ia_row:
            traits_data = ia_row["traits"]
            personality = []
            if traits_data:
                try:
                    personality = (
                        json.loads(traits_data)
                        if isinstance(traits_data, str)
                        else traits_data
                    )
                except (json.JSONDecodeError, TypeError):
                    personality = []

            ia = {
                "nom": ia_row["name"],
                "personnalite": personality if isinstance(personality, list) else [],
                "quirk": ia_row["quirk"],
            }

        protagoniste = None
        if protag_row:
            protagoniste = {
                "nom": protag_row["name"],
                "credits": protag_row["credits"] or 0,
            }

        arrivee = None
        if arrival and arrival["events"]:
            events = arrival["events"]
            arrivee = {
                "lieu": events.get("arrival_location"),
                "date": arrival["date"],
                "heure": events.get("hour"),
                "ambiance": events.get("initial_mood"),
            }

        return {
            "monde_cree": True,
            "monde": monde,
            "ia": ia,
            "protagoniste": protagoniste,
            "nb_personnages": counts.get("characters", 0),
            "nb_lieux": counts.get("locations", 0),
            "nb_organisations": counts.get("organizations", 0),
            "arrivee": arrivee,
        }

    # =========================================================================
    # WORLD DATA (pour sidebars)
    # =========================================================================

    async def load_npcs(self, game_id: UUID) -> list[dict]:
        """Charge les PNJs connus du protagoniste"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            characters = await reader.get_known_characters(conn)

            # Enrichir avec la localisation de chaque personnage
            result = []
            for c in characters:
                location = await reader.get_character_location(conn, c["id"])
                result.append(
                    {
                        "id": str(c["id"]),
                        "nom": c["name"],
                        "profession": c["profession"],
                        "lieu": location,
                        "relation": self._get_relation_label(c["relation_level"]),
                        "relation_level": c["relation_level"],
                        "description": c["physical_description"],
                    }
                )

        return result

    async def load_locations(self, game_id: UUID) -> list[dict]:
        """Charge les lieux connus du protagoniste"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            locations = await reader.get_known_locations(conn)

        return [
            {
                "id": str(loc["id"]),
                "nom": loc["name"],
                "type": loc["location_type"],
                "secteur": loc["sector"],
                "parent": loc["parent_location_name"],
                "accessible": loc["accessible"],
            }
            for loc in locations
        ]

    async def load_quests(self, game_id: UUID) -> list[dict]:
        """Charge les quêtes/arcs actifs"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            commitments = await reader.get_active_commitments(conn)

        return [
            {
                "id": str(c["id"]),
                "nom": c["objective"]
                or (c["description"][:50] if c["description"] else ""),
                "description": c["description"],
                "type": c["type"],
                "statut": "En cours",
                "priorite": self._get_priority(c["type"], c["deadline_cycle"]),
                "progression": c["progress"] or 0,
            }
            for c in commitments
        ]

    async def load_organizations(self, game_id: UUID) -> list[dict]:
        """Charge les organisations connues"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            organizations = await reader.get_known_organizations(conn)

        return [
            {
                "id": str(org["id"]),
                "nom": org["name"],
                "type": org["org_type"],
                "domaine": org["domain"],
                # "relation": org["protagonist_relation"],
            }
            for org in organizations
        ]

    async def load_chat_messages(self, game_id: UUID) -> list[dict]:
        """Charge l'historique des messages"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            messages = await reader.get_messages(conn, order="asc")

        return [
            {"role": m["role"], "content": m["content"], "cycle": m["cycle"]}
            for m in messages
        ]

    # =========================================================================
    # PROCESS INIT (World Generation)
    # =========================================================================

    async def process_init(self, game_id: UUID, world_gen: WorldGeneration) -> dict:
        """Peuple le Knowledge Graph avec la génération du monde"""
        populator = WorldPopulator(self.pool, game_id)
        await populator.populate(world_gen)

        arrival = world_gen.arrival_event

        # Extraire les attributs du protagoniste
        protagonist_attrs = {
            attr.key.value: attr.value for attr in world_gen.protagonist.attributes
        }

        return {
            "monde": {
                "nom": world_gen.world.name,
                "atmosphere": next(
                    (
                        a.value
                        for a in world_gen.world.attributes
                        if a.key.value == "atmosphere"
                    ),
                    "",
                ),
                "secteurs": world_gen.world.sectors,
            },
            "protagoniste": {
                "nom": world_gen.protagonist.name,
                "origine": protagonist_attrs.get("origin", ""),
                "raison_depart": protagonist_attrs.get("departure_reason", ""),
                "credits": int(protagonist_attrs.get("credits", 1400)),
            },
            "ia": {
                "nom": world_gen.personal_ai.name,
                "personnalite": next(
                    (
                        json.loads(a.value)
                        for a in world_gen.personal_ai.attributes
                        if a.key.value == "traits"
                    ),
                    [],
                ),
                "quirk": next(
                    (
                        a.value
                        for a in world_gen.personal_ai.attributes
                        if a.key.value == "quirk"
                    ),
                    "",
                ),
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

        reader = self._get_reader(game_id)
        populator = self._get_populator(game_id)

        async with self.pool.acquire() as conn:
            # Récupérer la date actuelle
            current_date = await reader.get_current_date(conn)

            # Gérer le changement de jour si présent
            new_date = current_date
            if narration.day_transition:
                dt = narration.day_transition
                new_date = getattr(dt, "new_date", None)

            # Mettre à jour cycle_summaries
            await populator.save_cycle_summary(conn, new_cycle, date=new_date)

            # Mettre à jour timestamp de la partie
            await populator.update_game_timestamp(conn)

        return {
            "cycle": new_cycle,
            "time": new_time,
            "location": location,
            "npcs_present": npcs,
            "date": new_date,
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
        date: str | None = None,
        time: str | None = None,
        location_ref: str | None = None,
        npcs_present_refs: list[str] | None = None,
        summary: str | None = None,
        tone_notes: str | None = None,
    ) -> tuple[UUID, UUID]:
        """Sauvegarde une paire de messages (user + assistant)"""
        populator = self._get_populator(game_id)

        async with self.pool.acquire() as conn:
            # Charger le registry pour résoudre les refs
            await populator.load_registry(conn)

            # Sauvegarder les messages
            return await populator.save_message_pair(
                conn,
                user_message,
                assistant_message,
                cycle,
                date,
                time,
                location_ref,
                npcs_present_refs,
                summary,
                tone_notes=tone_notes,
            )

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_message(self, game_id: UUID, keep_until_index: int) -> dict:
        """
        Rollback: supprime tous les messages à partir de keep_until_index (inclus).

        Exemple: messages = [user0, assistant0, user1, assistant1]
        - keep_until_index=2 → garde [user0, assistant0], supprime [user1, assistant1]
        - keep_until_index=0 → supprime tout
        """
        reader = self._get_reader(game_id)
        populator = self._get_populator(game_id)

        async with self.pool.acquire() as conn:
            # Récupérer tous les messages ordonnés
            messages = await reader.get_messages(conn, order="asc")

            if keep_until_index >= len(messages):
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
            await populator.delete_messages_by_ids(conn, ids_to_delete)

            # 2. Rollback du KG
            rollback_result = await populator.rollback_to_cycle(conn, target_cycle)

            # 3. Mettre à jour le timestamp
            await populator.update_game_timestamp(conn)

        return {
            "deleted": len(messages_to_delete),
            "target_cycle": target_cycle,
            "rollback_result": rollback_result,
        }

    # =========================================================================
    # HELPERS (privés)
    # =========================================================================

    @staticmethod
    def _get_relation_label(level: int | None) -> str:
        """Convertit le niveau de relation en label"""
        if level is None:
            return "Inconnu"
        if level >= 8:
            return "Ami proche"
        if level >= 6:
            return "Ami"
        if level >= 4:
            return "Connaissance"
        if level >= 2:
            return "Neutre"
        return "Hostile"

    @staticmethod
    def _get_priority(commitment_type: str, deadline: int | None) -> str:
        """Détermine la priorité d'une quête"""
        if deadline is not None:
            return "haute"
        if commitment_type == "arc":
            return "haute"
        if commitment_type in ("secret", "chekhov_gun"):
            return "normale"
        return "basse"
