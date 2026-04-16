"""
LDVELH - Game Service
Logique métier pour la gestion des parties
Utilise kg/reader.py et kg/populator.py pour l'accès BDD
"""

import json
import logging
from uuid import UUID

import asyncpg

from config import DEFAULT_STATS
from utils.json_utils import parse_json
from services.llm_service import compute_cost_from_stored
from kg.reader import KnowledgeGraphReader
from kg.populator import KnowledgeGraphPopulator
from kg.specialized_populator import WorldPopulator
from schema import WorldGeneration, NarrationOutput
from services.engine import get_engine
from schema.sse_payload import (
    AISummary,
    ArrivalSummary,
    ProtagonistSummary,
    WorldInfo,
    WorldSummary,
)

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class GameService:
    """Service principal pour la gestion des parties"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    def _get_reader(self, game_id: UUID) -> KnowledgeGraphReader:
        return KnowledgeGraphReader(self.pool, game_id)

    def _get_populator(self, game_id: UUID) -> KnowledgeGraphPopulator:
        return KnowledgeGraphPopulator(self.pool, game_id)

    async def verify_ownership(self, game_id: UUID, user_id: UUID) -> None:
        """Verify user owns the game. Raises 403 if not."""
        async with self.pool.acquire() as conn:
            owner = await conn.fetchval(
                "SELECT user_id FROM games WHERE id = $1 AND active = true", game_id
            )
        if owner is None:
            raise HTTPException(status_code=404, detail="Game not found")
        if owner != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

    # =========================================================================
    # CRUD PARTIES
    # =========================================================================

    async def list_games(self, user_id: UUID) -> list[dict]:
        """List active games for a specific user."""
        reader = KnowledgeGraphReader(self.pool)
        async with self.pool.acquire() as conn:
            games = await reader.list_games(conn, active_only=True, user_id=user_id)

        return [
            {
                "id": str(g["id"]),
                "name": g["name"],
                "current_cycle": g["current_cycle"],
                "day": g["current_date"] or 1,
                "engine": g.get("engine", "none"),
                "created_at": g["created_at"].isoformat() if g["created_at"] else None,
                "updated_at": g["updated_at"].isoformat() if g["updated_at"] else None,
            }
            for g in games
        ]

    async def create_game(self, user_id: UUID, engine: str | None = None) -> UUID:
        """Create a new game for the given user."""
        populator = KnowledgeGraphPopulator(self.pool)
        async with self.pool.acquire() as conn:
            game_id = await populator.create_game(conn, "Nouvelle partie", user_id=user_id)
            if engine and engine != "none":
                await populator.set_engine(conn, engine, world_config=None)
            return game_id

    async def delete_game(self, game_id: UUID) -> None:
        populator = self._get_populator(game_id)
        async with self.pool.acquire() as conn:
            await populator.delete_game(conn)

    async def rename_game(self, game_id: UUID, name: str) -> None:
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
            game = await reader.get_game(conn)
            if not game or not game["active"]:
                raise ValueError(f"Partie {game_id} introuvable")

            world_created = await reader.is_world_created(conn)

            stats = await self._load_protagonist_stats(reader, conn)
            inventory = await self._load_inventory(reader, conn)
            ai_data = await self._load_companion(reader, conn)

            # Engine stats
            engine_type = game.get("engine", "none")
            engine = get_engine(engine_type)
            engine_stats = None
            if engine_type != "none":
                engine_stats = await engine.get_vitals_display(conn, game_id)

            # Cycle info from games table
            location_name = await reader.get_current_location_name(conn)

        game_data = {
            "id": game_id,
            "name": game["name"],
            "current_cycle": game["current_cycle"] or 0,
            "game_date": game["current_date"] or "Jour 1",
            "time": game["current_time"] or "08h00",
            "current_location": location_name,
            "npcs_present": [],  # Ephemeral, set by narration response
            "last_extraction_time": game.get("last_extraction_time"),
            "engine": engine_type,
            "engine_locked": game.get("engine_locked", False),
        }

        player_data = {**stats, "inventory": inventory, "engine_stats": engine_stats}

        from services.state_normalizer import game_state_to_dict, normalize_game_state

        state = normalize_game_state(
            game_data=game_data,
            player_data=player_data,
            ai_data=ai_data,
        )

        result = game_state_to_dict(state)
        result["world_created"] = world_created
        return result

    async def _load_protagonist_stats(self, reader: KnowledgeGraphReader, conn) -> dict:
        row = await reader.get_protagonist_stats(conn)
        credits = DEFAULT_STATS["credits"]
        if row and row["credits"] is not None:
            credits = int(row["credits"])
        return {"credits": credits}

    async def _load_inventory(self, reader: KnowledgeGraphReader, conn) -> list[dict]:
        rows = await reader.get_inventory(conn)
        return [
            {
                "name": r["object_name"],
                "category": r.get("category") or "misc",
                "quantity": r.get("quantity") or 1,
                "base_value": r.get("base_value") or 0,
            }
            for r in rows
        ]

    async def _load_companion(
        self, reader: KnowledgeGraphReader, conn
    ) -> dict | None:
        row = await reader.get_companion(conn)
        if not row:
            return None

        traits = row.get("traits") or []
        return {
            "name": row["name"],
            "personality": traits if isinstance(traits, list) else [],
            "voice": row.get("voice"),
            "quirk": row.get("quirk"),
        }

    async def load_world_info(self, game_id: UUID) -> dict | None:
        """Reconstruct world presentation info from the KG, matching WorldInfo model."""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            if not await reader.is_world_created(conn):
                return None

            game = await reader.get_game(conn)
            counts = await reader.get_entity_counts_by_type(conn)
            ia_row = await reader.get_companion(conn)
            protag_row = await reader.get_protagonist(conn)
            arrival = await reader.get_arrival_event(conn)

        world_info = WorldInfo(
            world=WorldSummary(
                name=(game.get("world_name") or "Station") if game else "Station",
                atmosphere=(game.get("world_atmosphere") or "") if game else "",
                sectors=(game.get("world_seed_words") or []) if game else [],
            ),
            protagonist=ProtagonistSummary(
                name=protag_row["name"] if protag_row else "Inconnu",
                credits=protag_row.get("credits") or 0 if protag_row else 0,
            ),
            ai=AISummary(
                name=ia_row["name"] if ia_row else "IA",
                personality=(
                    ia_row.get("traits") or []
                    if ia_row and isinstance(ia_row.get("traits"), list)
                    else []
                ),
                quirk=ia_row.get("quirk") or "" if ia_row else "",
            ),
            npc_count=counts.get("characters", 0),
            location_count=counts.get("locations", 0),
            org_count=counts.get("organizations", 0),
            arrival=ArrivalSummary(
                location=arrival.get("arrival_description", ""),
                date=arrival.get("date"),
                time=arrival.get("time"),
                mood=arrival.get("initial_mood"),
            )
            if arrival
            else None,
        )

        return world_info.model_dump(exclude_none=True)

    # =========================================================================
    # WORLD DATA (pour sidebars)
    # =========================================================================

    async def load_npcs(self, game_id: UUID) -> list[dict]:
        """Charge les PNJs connus du protagoniste"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            characters = await reader.get_known_characters(conn)

        return [
            {
                "id": str(c["id"]),
                "name": c["name"],
                "occupation": c.get("occupation"),
                "location": c.get("workplace_name") or c.get("usual_location"),
                "relationship": self._get_relation_label(c.get("relation_level")),
                "relation_level": c.get("relation_level"),
                "description": c.get("description"),
            }
            for c in characters
        ]

    async def load_locations(self, game_id: UUID) -> list[dict]:
        """Charge les lieux"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            locations = await reader.get_locations(conn)

        return [
            {
                "id": str(loc["id"]),
                "name": loc["name"],
                "type": loc.get("location_type"),
                "sector": loc.get("sector"),
                "parent": loc.get("parent_location_name"),
                "accessible": loc.get("accessible", True),
            }
            for loc in locations
        ]

    async def load_quests(self, game_id: UUID) -> list[dict]:
        """Charge les arcs narratifs actifs"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            arcs = await reader.get_active_arcs(conn)

        return [
            {
                "id": str(a["id"]),
                "name": a["title"],
                "description": a.get("description") or "",
                "type": a.get("domain") or "personal",
                "status": "En cours",
                "priority": "high" if a.get("deadline_cycle") else "normal",
                "progress": a.get("progress") or 0,
            }
            for a in arcs
        ]

    async def load_organizations(self, game_id: UUID) -> list[dict]:
        """Charge les organisations"""
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            organizations = await reader.get_organizations(conn)

        return [
            {
                "id": str(org["id"]),
                "name": org["name"],
                "type": org.get("org_type"),
                "domain": org.get("domain"),
            }
            for org in organizations
        ]

    async def load_chat_messages(self, game_id: UUID) -> list[dict]:
        """Load chat messages for frontend display.

        Filters out protocol tokens (__ARRIVEE__ etc.) from user messages —
        these are kept in DB for LLM history but not shown to the user.
        """
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            messages = await reader.get_messages(conn, order="asc")

        result = []
        for m in messages:
            # Hide protocol user messages from frontend
            if m["role"] == "user" and m["content"].strip().startswith("__"):
                continue

            msg = {
                "role": m["role"],
                "content": m["content"],
                "cycle": m.get("cycle"),
                "game_date": m.get("game_date"),
                "time": m.get("time"),
                "location": m.get("location_name"),
            }
            # Include roll data from mechanic_rolls join
            roll_details = m.get("roll_details")
            if roll_details:
                msg["roll"] = roll_details if isinstance(roll_details, dict) else parse_json(roll_details)
            deltas = parse_json(m.get("narrator_deltas"))
            if deltas and isinstance(deltas, dict):
                if deltas.get("cost"):
                    cost_data = dict(deltas["cost"])
                    if "cost_usd" not in cost_data:
                        cost_data["cost_usd"] = compute_cost_from_stored(cost_data)
                    msg["cost"] = cost_data
                if deltas.get("extraction_cost"):
                    ext_cost = dict(deltas["extraction_cost"])
                    if "cost_usd" not in ext_cost:
                        ext_cost["cost_usd"] = compute_cost_from_stored(ext_cost)
                    msg["extraction_cost"] = ext_cost
            result.append(msg)
        return result

    # =========================================================================
    # PROCESS INIT (World Generation)
    # =========================================================================

    async def process_init(self, game_id: UUID, world_gen: WorldGeneration) -> dict:
        """Peuple le Knowledge Graph avec la génération du monde"""
        populator = WorldPopulator(self.pool, game_id)
        await populator.populate(world_gen)

        arrival = world_gen.arrival_event

        return {
            "world": {
                "name": world_gen.world.name,
                "atmosphere": world_gen.world.atmosphere or "",
                "sectors": world_gen.world.sectors,
            },
            "protagonist": {
                "name": world_gen.protagonist.name,
                "origin": world_gen.protagonist.origin or "",
                "departure_reason": world_gen.protagonist.departure_reason.value
                if hasattr(world_gen.protagonist.departure_reason, "value")
                else str(world_gen.protagonist.departure_reason),
                "credits": world_gen.protagonist.credits,
            },
            "ai": {
                "name": world_gen.companion.name,
                "personality": world_gen.companion.traits,
                "quirk": world_gen.companion.quirk or "",
            },
            "npc_count": len(world_gen.characters),
            "location_count": len(world_gen.locations),
            "org_count": len(world_gen.organizations),
            "inventory_count": len(world_gen.inventory),
            "arrival": {
                "location": arrival.arrival_location_ref,
                "date": arrival.arrival_date,
                "time": arrival.time,
                "mood": arrival.initial_mood,
                "immediate_need": arrival.immediate_need,
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
        """Traite la sortie du narrateur et met à jour l'état du jeu"""
        new_cycle = current_cycle + 1 if narration.day_transition else current_cycle
        new_time = narration.time.new_time if narration.time else ""
        location = narration.current_location
        npcs = narration.npcs_present or []

        reader = self._get_reader(game_id)
        populator = self._get_populator(game_id)

        async with self.pool.acquire() as conn:
            # Current date
            current_date = await reader.get_current_date(conn)
            new_date = current_date
            if narration.day_transition:
                new_date = getattr(narration.day_transition, "new_date", current_date)

            # Resolve location for game state update
            location_id = None
            resolved_location = location
            if location:
                location_id = await conn.fetchval(
                    "SELECT id FROM locations WHERE game_id = $1"
                    " AND LOWER(name) = LOWER($2)",
                    game_id,
                    location,
                )
                if location_id:
                    old_loc = await reader.get_current_location_name(conn)
                    if old_loc and old_loc.lower() != location.lower():
                        logger.info(
                            f"[GAME] Location changed: '{old_loc}' → '{location}'"
                        )
                else:
                    # Create a stub location (will be fully populated during extraction)
                    location_id = await conn.fetchval(
                        """INSERT INTO locations (game_id, name, created_cycle)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (game_id, name) DO NOTHING
                        RETURNING id""",
                        game_id, location, new_cycle,
                    )
                    if not location_id:
                        # Race condition: created between check and insert
                        location_id = await conn.fetchval(
                            "SELECT id FROM locations WHERE game_id = $1"
                            " AND LOWER(name) = LOWER($2)",
                            game_id, location,
                        )
                    logger.info(
                        f"[GAME] Created stub location '{location}' "
                        f"(cycle {new_cycle}), to be enriched during extraction"
                    )

            # Create stubs for events mentioned
            for evt in narration.events_mentioned:
                await populator.create_stub_event(conn, evt, new_cycle)

            # Update game state
            await populator.update_game_state(
                conn,
                cycle=new_cycle,
                date=new_date,
                time=new_time,
                location_id=location_id,
            )

            # Reset detail_requests on day transition (new cycle = fresh slate)
            if narration.day_transition:
                await populator.clear_detail_requests(conn)

        return {
            "cycle": new_cycle,
            "time": new_time,
            "location": resolved_location,
            "npcs_present": npcs,
            "date": new_date,
        }

    # =========================================================================
    # NARRATOR DELTAS (live state changes)
    # =========================================================================

    async def apply_narrator_deltas(
        self, game_id: UUID, narration: NarrationOutput, cycle: int
    ) -> dict:
        """Apply credit deltas and entity reveals from narrator output immediately."""
        populator = self._get_populator(game_id)
        results = {"credits": None}

        async with self.pool.acquire() as conn:
            if narration.credit_delta:
                cd = narration.credit_delta
                success, new_balance, error = await populator.credit_transaction(
                    conn, cd.amount, cycle, cd.description
                )
                results["credits"] = {
                    "amount": cd.amount,
                    "new_balance": new_balance,
                    "error": error,
                }

            for reveal in narration.entity_reveals:
                if reveal.entity_type == "character":
                    await populator.mark_character_known(
                        conn, reveal.current_name, reveal.real_name
                    )
                elif reveal.entity_type == "location":
                    await populator.mark_location_accessible(conn, reveal.current_name)

            # Store narrative seeds
            for seed_text in (narration.narrative_seeds or [])[:2]:
                if seed_text and seed_text.strip():
                    await populator.save_seed(conn, cycle, seed_text.strip())

            # Archive stale seeds
            await populator.archive_stale_seeds(conn, cycle)

            # Fate Core: compel FP adjustment
            if narration.compel_result in ("accepted", "refused"):
                try:
                    fate_row = await conn.fetchrow(
                        "SELECT fate_points FROM character_fate WHERE game_id = $1",
                        game_id,
                    )
                    if fate_row is not None:
                        fp = fate_row["fate_points"]
                        if narration.compel_result == "accepted":
                            new_fp = fp + 1
                        else:  # refused
                            new_fp = max(0, fp - 1)
                        await conn.execute(
                            "UPDATE character_fate SET fate_points = $1 WHERE game_id = $2",
                            new_fp, game_id,
                        )
                        results["compel"] = {
                            "result": narration.compel_result,
                            "aspect": narration.compel_aspect,
                            "fp_change": 1 if narration.compel_result == "accepted" else -1,
                            "new_fp": new_fp,
                        }
                except Exception as e:
                    logger.warning(f"[COMPEL] FP adjustment failed: {e}")

        return results

    async def store_info_requests(
        self, game_id: UUID, info_requests: list[str]
    ) -> None:
        """Store narrator info requests for next turn context loading."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE games SET detail_requests = $1 WHERE id = $2",
                info_requests,
                game_id,
            )

    # =========================================================================
    # MULTI-TURN CONVERSATION
    # =========================================================================

    # Number of past cycles to include in conversation history
    HISTORY_CYCLES = 2

    async def build_llm_messages(
        self,
        game_id: UUID,
        current_cycle: int,
        context_prompt: str,
        json_history: bool = False,
    ) -> list[dict]:
        """
        Build the messages array for the LLM API.

        Structure:
        - Past messages from last 2 cycles (user=raw input, assistant=display_text)
        - cache_control on last message of cycle N-1 (stable prefix)
        - Final user message = context_prompt (world state + player action)

        If json_history=True, wrap assistant messages in a JSON envelope
        so the model sees consistent JSON responses.
        """
        reader = self._get_reader(game_id)

        async with self.pool.acquire() as conn:
            min_cycle = max(1, current_cycle - self.HISTORY_CYCLES + 1)
            rows = await reader.get_messages_for_cycles(
                conn, from_cycle=min_cycle, to_cycle=current_cycle
            )

        messages: list[dict] = []
        last_prev_cycle_idx = -1

        for row in rows:
            content = row["content"]
            if row["role"] == "user":
                # Enrich history user messages with time/location context
                meta_parts = []
                if row.get("cycle"):
                    meta_parts.append(f"Cycle {row['cycle']}")
                if row.get("time"):
                    meta_parts.append(row["time"])
                if row.get("location_name"):
                    meta_parts.append(row["location_name"])
                if meta_parts:
                    content = f"[{' — '.join(meta_parts)}]\n{content}"
            elif row["role"] == "assistant":
                # Append arc progression info from narrator_deltas hints
                arc_suffix = self._extract_arc_suffix(row.get("narrator_deltas"))
                if arc_suffix:
                    content = f"{content}\n\n{arc_suffix}"
                if json_history:
                    content = json.dumps(
                        {"narrative_text": content}, ensure_ascii=False
                    )
            msg = {"role": row["role"], "content": content}
            messages.append(msg)

            if row["cycle"] < current_cycle:
                last_prev_cycle_idx = len(messages) - 1

        # Apply cache_control on last message of cycle N-1 (stable prefix)
        if last_prev_cycle_idx >= 0:
            msg = messages[last_prev_cycle_idx]
            messages[last_prev_cycle_idx] = {
                "role": msg["role"],
                "content": [
                    {
                        "type": "text",
                        "text": msg["content"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }

        # Context prompt as final user message
        messages.append({"role": "user", "content": context_prompt})

        return messages

    @staticmethod
    def _extract_arc_suffix(narrator_deltas) -> str | None:
        """Extract arc progression info from narrator_deltas for history context."""
        if not narrator_deltas:
            return None
        if isinstance(narrator_deltas, str):
            import json

            try:
                narrator_deltas = json.loads(narrator_deltas)
            except (json.JSONDecodeError, TypeError):
                return None

        hints = narrator_deltas.get("hints") or {}
        parts = []
        for arc in hints.get("arc_advanced") or []:
            parts.append(f"{arc} ↑")
        for arc in hints.get("arc_resolved") or []:
            parts.append(f"{arc} ✓")
        if hints.get("new_arc_created"):
            parts.append("nouvel arc")
        if not parts:
            return None
        return f"[Arcs: {', '.join(parts)}]"

    # =========================================================================
    # MESSAGES
    # =========================================================================

    async def save_messages(
        self,
        game_id: UUID,
        user_message: str,
        assistant_message: str,
        cycle: int,
        time: str | None = None,
        game_date: str | None = None,
        location_ref: str | None = None,
        narrator_deltas: dict | None = None,
        engine_snapshot: dict | None = None,
        narrator_context: list | None = None,
    ) -> tuple[UUID, UUID]:
        """Save a user + assistant message pair."""
        populator = self._get_populator(game_id)

        async with self.pool.acquire() as conn:
            # Get or create active conversation
            conv_id = await populator.get_active_conversation(conn)
            if not conv_id:
                conv_id = await populator.create_conversation(conn, cycle)

            # Get next sequence number
            max_seq = await conn.fetchval(
                "SELECT COALESCE(MAX(sequence), 0) FROM messages"
                " WHERE conversation_id = $1",
                conv_id,
            )

            # Save user message
            user_id = await populator.save_message(
                conn,
                conv_id,
                "user",
                user_message,
                sequence=max_seq + 1,
                cycle=cycle,
                time=time,
                game_date=game_date,
                location_ref=location_ref,
            )
            # Save assistant message (with narrator deltas + engine snapshot)
            assistant_id = await populator.save_message(
                conn,
                conv_id,
                "assistant",
                assistant_message,
                sequence=max_seq + 2,
                cycle=cycle,
                time=time,
                game_date=game_date,
                location_ref=location_ref,
                narrator_deltas=narrator_deltas,
                engine_snapshot=engine_snapshot,
                narrator_context=narrator_context,
            )

            return user_id, assistant_id

    async def log_mechanic_roll(
        self,
        game_id: UUID,
        message_id: UUID | None,
        engine: str,
        skill_used: str | None,
        roll_details: dict,
        outcome: str,
        complication: bool,
        cycle: int | None,
    ) -> UUID:
        """Log a mechanical roll result linked to an assistant message.

        Returns the roll ID (UUID).
        """
        populator = self._get_populator(game_id)
        async with self.pool.acquire() as conn:
            return await populator.log_mechanic_roll(
                conn, game_id, message_id, engine,
                skill_used, roll_details, outcome, complication, cycle,
            )

    async def load_pending_roll(self, game_id: UUID, roll_id: UUID) -> dict | None:
        """Load a pending mechanic roll by ID for aspect invocation resume."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, roll_details, outcome, engine, skill_used, cycle
                FROM mechanic_rolls
                WHERE id = $1 AND game_id = $2 AND message_id IS NULL""",
                roll_id,
                game_id,
            )
            if not row:
                return None
            details = row["roll_details"]
            if isinstance(details, str):
                details = parse_json(details)
            return {
                "id": row["id"],
                "roll_details": details,
                "outcome": row["outcome"],
                "engine": row["engine"],
                "skill_used": row["skill_used"],
                "cycle": row["cycle"],
            }

    async def update_mechanic_roll(
        self,
        roll_id: UUID,
        roll_details: dict,
        outcome: str,
        message_id: UUID | None = None,
    ) -> None:
        """Update a mechanic roll after aspect invocation."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE mechanic_rolls
                SET roll_details = $1::jsonb, outcome = $2, message_id = $3
                WHERE id = $4""",
                json.dumps(roll_details),
                outcome,
                message_id,
                roll_id,
            )

    # =========================================================================
    # ROLLBACK
    # =========================================================================

    async def rollback_to_message(self, game_id: UUID, keep_until_index: int) -> dict:
        """
        Rollback: delete all messages from keep_until_index onwards.
        Also restores engine state from the last remaining message's snapshot.
        """
        reader = self._get_reader(game_id)
        populator = self._get_populator(game_id)

        async with self.pool.acquire() as conn:
            messages = await reader.get_messages(conn, order="asc")

            if keep_until_index >= len(messages):
                return {"deleted": 0, "target_cycle": None, "rollback_result": {}}

            messages_to_delete = messages[keep_until_index:]
            if not messages_to_delete:
                return {"deleted": 0, "target_cycle": None, "rollback_result": {}}

            target_cycle = (
                messages[keep_until_index - 1]["cycle"] if keep_until_index > 0 else 0
            )

            # Delete messages
            ids_to_delete = [m["id"] for m in messages_to_delete]
            await conn.execute(
                "DELETE FROM messages WHERE id = ANY($1)",
                ids_to_delete,
            )

            # Rollback KG
            rollback_result = await populator.rollback_to_cycle(conn, target_cycle)

            # Restore full game state from last remaining assistant message
            restore_date = None
            restore_time = None
            restore_location_id = None
            engine_snapshot = None
            if keep_until_index > 0:
                for i in range(keep_until_index - 1, -1, -1):
                    m = messages[i]
                    if m["role"] == "assistant":
                        restore_date = m.get("game_date")
                        restore_time = m.get("time")
                        restore_location_id = m.get("location_id")
                        engine_snapshot = m.get("engine_snapshot")
                        break

            # Explicit UPDATE to reset all state fields (including NULLs)
            await conn.execute(
                """UPDATE games
                   SET current_cycle = $2,
                       "current_date" = $3,
                       "current_time" = $4,
                       current_location_id = $5,
                       last_extraction_time = NULL,
                       updated_at = NOW()
                   WHERE id = $1""",
                game_id, target_cycle, restore_date,
                restore_time, restore_location_id,
            )

            # Restore engine state from snapshot
            if engine_snapshot:
                game = await reader.get_game(conn)
                engine_type = game.get("engine", "none") if game else "none"
                if engine_type != "none":
                    engine = get_engine(engine_type)
                    await engine.restore_snapshot(conn, game_id, engine_snapshot)

        return {
            "deleted": len(messages_to_delete),
            "target_cycle": target_cycle,
            "rollback_result": rollback_result,
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _get_relation_label(level: int | None) -> str:
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
