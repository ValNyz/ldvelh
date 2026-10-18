"""
LDVELH - Game Service
Logique métier pour la gestion des parties
Utilise kg/reader.py et kg/populator.py pour l'accès BDD
"""

import json
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

import asyncpg

from config import DEFAULT_STATS
from domain.errors import GameAccessDenied, GameNotFound
from utils.json_utils import parse_json
from llm.usage import cost_from_stored
from kg.reader import KnowledgeGraphReader
from kg.populator import KnowledgeGraphPopulator
from kg.specialized_populator import WorldPopulator
from schema import DEFAULT_GAME_TIME, EngineType, WorldGeneration
from services.engine import get_engine
from services.pending_roll import load_pending_roll
from repos import games as games_repo
from repos import turns
from schema.sse_payload import (
    AISummary,
    ArrivalSummary,
    ProtagonistSummary,
    WorldInfo,
    WorldSummary,
)

logger = logging.getLogger(__name__)


def _stored_info_requests(narrator_deltas) -> list[str]:
    """The detail requests a stored turn left behind; none for messages saved before #64."""
    if isinstance(narrator_deltas, str):
        narrator_deltas = parse_json(narrator_deltas)
    if not isinstance(narrator_deltas, dict):
        return []
    return [r for r in narrator_deltas.get("info_requests") or [] if isinstance(r, str)]


class RollbackRejected(ValueError):
    """The requested rollback is refused; `reason` names why (player text lives in api/)."""

    ARRIVAL_SCENE = "arrival_scene"  # would remove the arrival scene (#11)

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class GameService:
    """Service principal pour la gestion des parties"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    def _get_reader(self, game_id: UUID) -> KnowledgeGraphReader:
        return KnowledgeGraphReader(self.pool, game_id)

    def _get_populator(self, game_id: UUID) -> KnowledgeGraphPopulator:
        return KnowledgeGraphPopulator(self.pool, game_id)

    async def verify_ownership(self, game_id: UUID, user_id: UUID) -> None:
        """Verify user owns the game: GameNotFound if missing, GameAccessDenied if not theirs."""
        async with self.pool.acquire() as conn:
            owner = await conn.fetchval(
                "SELECT user_id FROM games WHERE id = $1 AND active = true", game_id
            )
        if owner is None:
            raise GameNotFound(game_id)
        if owner != user_id:
            raise GameAccessDenied(game_id)

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
                "engine": g["engine"],
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
                await games_repo.set_engine(conn, game_id, engine, world_config=None)
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
            engine_type = EngineType(game["engine"])  # coerced by the reader
            engine = get_engine(engine_type)
            engine_stats = None
            if engine_type != "none":
                engine_stats = await engine.get_vitals_display(conn, game_id)
            # A roll waiting for an aspect invocation comes back with the game (#32).
            pending_roll = await load_pending_roll(conn, game_id, engine)

            # Cycle info from games table
            location_name = await reader.get_current_location_name(conn)

        game_data = {
            "id": game_id,
            "name": game["name"],
            "current_cycle": game["current_cycle"] or 0,
            "game_date": game["current_date"] or "Jour 1",
            "time": game["current_time"] or DEFAULT_GAME_TIME,
            "current_location": location_name,
            "npcs_present": [],  # Ephemeral, set by narration response
            "last_extraction_time": game.get("last_extraction_time"),
            "engine": engine_type.value,
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
        result["pending_roll"] = pending_roll.offer() if pending_roll else None
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
                "intensity": a.get("intensity") or 3,
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
                "id": str(m["id"]),
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
                        cost_data["cost_usd"] = cost_from_stored(cost_data)
                    msg["cost"] = cost_data
                if deltas.get("extraction_cost"):
                    ext_cost = dict(deltas["extraction_cost"])
                    if "cost_usd" not in ext_cost:
                        ext_cost["cost_usd"] = cost_from_stored(ext_cost)
                    msg["extraction_cost"] = ext_cost
            result.append(msg)
        return result

    # =========================================================================
    # PROCESS INIT (World Generation)
    # =========================================================================

    async def process_init(self, game_id: UUID, world_gen: WorldGeneration,
                           finalize: Callable[[asyncpg.Connection], Awaitable[None]] | None = None,
                           conn: asyncpg.Connection | None = None) -> dict:
        """Peuple le Knowledge Graph avec la génération du monde.

        `finalize(conn)` runs in the same transaction, after the world (atomic save).
        `conn`: a connection the caller already holds (and releases), else one from the pool.
        """
        populator = WorldPopulator(self.pool, game_id)
        await populator.populate(world_gen, finalize=finalize, conn=conn)

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
    # MULTI-TURN CONVERSATION
    # =========================================================================

    # Number of past cycles to include in conversation history
    HISTORY_CYCLES = 2

    # Bound the narrator history so a long in-game day cannot grow the prompt
    # without limit (#21): at most 80 messages / ~30k tokens (estimated as
    # len(text) // 4). Truncation drops whole blocks of HISTORY_TRIM_BLOCK
    # messages from the oldest end, so the kept prefix stays identical for many
    # consecutive turns and the provider's history cache keeps hitting.
    HISTORY_MAX_MESSAGES = 80
    HISTORY_TOKEN_BUDGET = 30_000
    HISTORY_TRIM_BLOCK = 20

    @classmethod
    def _trim_history(cls, messages: list[dict]) -> list[dict]:
        """Drop the oldest messages in blocks until both budgets fit; start on a user message."""
        costs = [len(m["content"]) // 4 for m in messages]
        total = sum(costs)
        start = 0
        while start < len(messages) and (
            len(messages) - start > cls.HISTORY_MAX_MESSAGES
            or total > cls.HISTORY_TOKEN_BUDGET
        ):
            end = min(start + cls.HISTORY_TRIM_BLOCK, len(messages))
            total -= sum(costs[start:end])
            start = end
        if start >= len(messages) > 0:
            # Messages so large that no block-aligned cut fits: cut message by message.
            start = 0
            while start < len(messages) - 1 and sum(costs[start:]) > cls.HISTORY_TOKEN_BUDGET:
                start += 1
        kept = messages[start:]
        while kept and kept[0]["role"] != "user":
            kept = kept[1:]
        if len(kept) < len(messages):
            logger.info(
                f"[History] truncated: dropped {len(messages) - len(kept)}, "
                f"kept {len(kept)}, ~{sum(len(m['content']) // 4 for m in kept)} tokens"
            )
        return kept

    @staticmethod
    def _apply_cache_breakpoints(messages: list[dict], enabled: bool,
                                 prev_cycle_idx: int) -> list[dict]:
        """Anthropic-only: mark the end of cycle N-1 and the last history message."""
        if not enabled or not messages:
            return messages
        marks = {len(messages) - 1}
        if 0 <= prev_cycle_idx < len(messages):
            marks.add(prev_cycle_idx)
        return [
            {"role": m["role"], "content": [{
                "type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"},
            }]} if i in marks else m
            for i, m in enumerate(messages)
        ]

    async def build_llm_messages(
        self,
        game_id: UUID,
        current_cycle: int,
        context_prompt: str,
        json_history: bool = False,
        cache_control: bool = False,
    ) -> list[dict]:
        """
        Build the messages array for the LLM API.

        Structure:
        - Past messages from last 2 cycles (user=raw input, assistant=display_text),
          bounded to 80 messages / ~30k tokens (trimmed by blocks of 20) and starting on
          a user message
        - Only if cache_control=True (provider supports it): cache breakpoints on
          the last message of cycle N-1 and on the last history message
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
            messages.append(
                {"role": row["role"], "content": content, "_cycle": row["cycle"]}
            )

        messages = self._trim_history(messages)
        prev_cycle_idx = max(
            (i for i, m in enumerate(messages) if m.get("_cycle", current_cycle) < current_cycle),
            default=-1,
        )
        messages = [{"role": m["role"], "content": m["content"]} for m in messages]
        messages = self._apply_cache_breakpoints(messages, cache_control, prev_cycle_idx)

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
    # ROLLBACK
    # =========================================================================

    async def rollback_to_message(
        self, game_id: UUID, message_id: UUID | None = None, keep_until_index: int | None = None
    ) -> dict:
        """
        Rollback: delete a message and everything after it.
        Accepts either message_id (preferred) or keep_until_index (legacy).
        Also restores engine state from the last remaining message's snapshot.
        """
        reader = self._get_reader(game_id)
        populator = self._get_populator(game_id)

        async with self.pool.acquire() as conn:
            messages = await reader.get_messages(conn, order="asc")

            if message_id:
                # Find the index of the target message
                msg_id_str = str(message_id)
                cutoff = None
                for i, m in enumerate(messages):
                    if str(m["id"]) == msg_id_str:
                        cutoff = i
                        break
                if cutoff is None:
                    return {"deleted": 0, "target_cycle": None, "rollback_result": {}}
                keep_until_index = cutoff
            elif keep_until_index is None:
                return {"deleted": 0, "target_cycle": None, "rollback_result": {}}

            if keep_until_index >= len(messages):
                return {"deleted": 0, "target_cycle": None, "rollback_result": {}}

            messages_to_delete = messages[keep_until_index:]
            if not messages_to_delete:
                return {"deleted": 0, "target_cycle": None, "rollback_result": {}}

            # The arrival pair (protocol token + first narration) is never rolled back:
            # doing so would target cycle 0 and wipe the initial world (#11).
            if keep_until_index < 2:
                raise RollbackRejected(RollbackRejected.ARRIVAL_SCENE)

            target_cycle = messages[keep_until_index - 1]["cycle"]

            # Reverse credit deltas from messages being deleted
            credit_reversal = 0
            for m in messages_to_delete:
                deltas = m.get("narrator_deltas")
                if deltas:
                    if isinstance(deltas, str):
                        deltas = parse_json(deltas)
                    if isinstance(deltas, dict):
                        cd = deltas.get("credit_delta")
                        # A refused debit never touched the balance; rows from before
                        # the "applied" key existed count as applied.
                        if cd and isinstance(cd, dict) and cd.get("applied") is not False:
                            credit_reversal -= cd.get("amount", 0)

            # Restore full game state from last remaining assistant message
            restore_date = None
            restore_time = None
            restore_location_id = None
            restore_requests: list[str] = []
            engine_snapshot = None
            for i in range(keep_until_index - 1, -1, -1):
                m = messages[i]
                if m["role"] == "assistant":
                    restore_date = m.get("game_date")
                    restore_time = m.get("time")
                    restore_location_id = m.get("location_id")
                    restore_requests = _stored_info_requests(m.get("narrator_deltas"))
                    # Not part of get_messages (never sent to the client).
                    engine_snapshot = await reader.get_message_engine_snapshot(conn, m["id"])
                    break

            # All-or-nothing: a failure part-way must not leave messages deleted
            # and credits refunded while the KG still holds the later cycle (#11).
            async with conn.transaction():
                if credit_reversal != 0:
                    await conn.execute(
                        "UPDATE protagonists SET credits = credits + $1"
                        " WHERE game_id = $2",
                        credit_reversal, game_id,
                    )

                ids_to_delete = [m["id"] for m in messages_to_delete]
                await conn.execute(
                    "DELETE FROM messages WHERE id = ANY($1)",
                    ids_to_delete,
                )

                # Reset game state (current location included) before the KG delete,
                # so the game no longer points at locations about to be removed.
                await conn.execute(
                    """UPDATE games
                       SET current_cycle = $2,
                           "current_date" = $3,
                           "current_time" = $4,
                           current_location_id = $5,
                           detail_requests = $6,
                           last_extraction_time = NULL,
                           updated_at = NOW()
                       WHERE id = $1""",
                    game_id, target_cycle, restore_date,
                    restore_time, restore_location_id, restore_requests,
                )

                rollback_result = await populator.rollback_to_cycle(conn, target_cycle)
                await turns.expire_pending_rolls(conn, game_id)

                game = await reader.get_game(conn)
                engine_type = EngineType(game["engine"]) if game else EngineType.NONE
                if engine_type != "none":
                    if engine_snapshot is not None:  # {} is a valid empty turn state
                        engine = get_engine(engine_type)
                        await engine.restore_turn_state(conn, game_id, engine_snapshot)
                    else:  # legacy message saved before snapshots: engine state is kept
                        logger.warning(f"[ROLLBACK] No engine snapshot for game {game_id}, "
                                       "engine state kept")

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
