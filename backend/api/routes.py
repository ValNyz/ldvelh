"""
LDVELH - API Routes
Routes FastAPI principales
"""

import time
import json
import logging
import asyncio
from uuid import UUID

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Body, Depends
from prompts.narrator_prompt import (
    build_narrator_system_prompt,
    build_narrator_context_prompt,
)
from pydantic import BaseModel
from schema import NarrationOutput, WorldGeneration
from schema.engine import MechanicalDecision, MechanicalResult, RollResult
from services.engine import get_engine
from services.engine.mechanical_service import run_mechanical_step
from schema.sse_payload import (
    AISummary,
    ArrivalSummary,
    NarratorDeltasStored,
    ProtagonistSummary,
    SSEDonePayload,
    SSEGameState,
    SSEMeta,
    SSEUIHints,
    WorldInfo,
    WorldSummary,
)

from api.dependencies import get_pool, get_settings_dep, get_current_user
from api.streaming import SSEWriter, create_sse_response
from config import Settings
from prompts.world_generation_prompt import get_full_generation_prompt
from services.context_builder import ContextBuilder
from services.extraction import run_resolve_and_extract
from services.game_service import GameService
from services.llm_service import get_llm_service

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# HELPERS
# =============================================================================


async def _resolve_user_api_key(
    pool: asyncpg.Pool, user_id: UUID, provider_name: str
) -> str | None:
    """Look up the user's encrypted API key for a provider, decrypt it."""
    async with pool.acquire() as conn:
        prefs_raw = await conn.fetchval(
            "SELECT preferences FROM users WHERE id = $1", user_id
        )
    if not prefs_raw:
        return None

    prefs = prefs_raw if isinstance(prefs_raw, dict) else json.loads(prefs_raw)
    api_keys = prefs.get("api_keys", {})
    encrypted_key = api_keys.get(provider_name)
    if not encrypted_key:
        return None

    from utils.crypto import decrypt_value

    return decrypt_value(encrypted_key)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class GameState(BaseModel):
    """Client-side game state"""

    game: dict | None = None
    player: dict | None = None
    ai: dict | None = None
    world_created: bool = False


class ChatRequest(BaseModel):
    """Requête de chat"""

    message: str
    gameId: UUID
    gameState: GameState | None = None
    provider: str = "anthropic"
    model: str | None = None
    # Engine params (init mode only)
    engine: str | None = None  # "none", "narrative", "fate_core", "d6"
    world_config: dict | None = None  # genre, difficulty, hardcore, lore
    character_data: dict | None = None  # engine-specific character stats
    manual_entities: dict | None = None  # user-defined NPCs/locations/orgs
    # Fate Core aspect invocation resume
    roll_id: UUID | None = None  # pending roll to resume
    invoked_aspects: list[str] | None = None  # aspects invoked (+2 each)


class RollbackRequest(BaseModel):
    """Requête de rollback"""

    fromIndex: int


class RenameRequest(BaseModel):
    """Requête de renommage"""

    gameId: UUID
    name: str


# =============================================================================
# GET ENDPOINTS
# =============================================================================


@router.get("/games")
async def list_games(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List active games for the current user."""
    service = GameService(pool)
    games = await service.list_games(user["id"])
    return {"games": games}


@router.get("/games/{game_id}")
async def load_game(
    game_id: UUID,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Load a game (with ownership check)."""
    service = GameService(pool)
    await service.verify_ownership(game_id, user["id"])

    state = await service.load_game_state(game_id)
    messages = await service.load_chat_messages(game_id)

    world_info = None
    if state.get("world_created") and not messages:
        world_info = await service.load_world_info(game_id)

    return {
        "state": state,
        "messages": messages,
        "world_info": world_info,
    }


class CreateGameRequest(BaseModel):
    """Optional params for game creation."""

    engine: str | None = None  # "none", "narrative", "fate_core", "d6"


@router.post("/games")
async def create_game(
    request: CreateGameRequest = Body(default=None),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Create a new game for the current user."""
    service = GameService(pool)
    engine = request.engine if request else None
    game_id = await service.create_game(user["id"], engine=engine)
    return {"gameId": str(game_id)}


@router.delete("/games/{game_id}")
async def delete_game(
    game_id: UUID,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Delete a game (with ownership check)."""
    service = GameService(pool)
    await service.verify_ownership(game_id, user["id"])
    await service.delete_game(game_id)
    return {"success": True}


@router.patch("/games/{game_id}")
async def rename_game(
    game_id: UUID,
    request: RenameRequest,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Rename a game (with ownership check)."""
    service = GameService(pool)
    await service.verify_ownership(game_id, user["id"])
    await service.rename_game(game_id, request.name)
    return {"success": True}


@router.get("/games/{game_id}/world")
async def get_world_data(
    game_id: UUID,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Get world data for sidebars (with ownership check)."""
    service = GameService(pool)
    await service.verify_ownership(game_id, user["id"])

    npcs = await service.load_npcs(game_id)
    locations = await service.load_locations(game_id)
    quests = await service.load_quests(game_id)
    organizations = await service.load_organizations(game_id)

    return {
        "npcs": npcs,
        "locations": locations,
        "quests": quests,
        "organizations": organizations,
    }


# =============================================================================
# SESSION COST ENDPOINT
# =============================================================================


@router.get("/session/cost")
async def session_cost(user: dict = Depends(get_current_user)):
    """Return accumulated token usage and cost for this server session."""
    llm_service = get_llm_service()
    return llm_service.cost_tracker.get_summary()


@router.get("/providers")
async def list_providers(user: dict = Depends(get_current_user)):
    """List available LLM providers and their models."""
    from services.llm_providers import get_provider_catalog

    return get_provider_catalog()


# =============================================================================
# ROLLBACK ENDPOINT
# =============================================================================


# 2. Remplacer le endpoint rollback
@router.post("/games/{game_id}/rollback")
async def rollback_game(
    game_id: UUID,
    request: RollbackRequest,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Rollback to a specific message (with ownership check)."""
    service = GameService(pool)
    await service.verify_ownership(game_id, user["id"])

    # Acquire game lock to prevent race with in-flight extraction
    lock = _get_game_lock(game_id)
    async with lock:
        result = await service.rollback_to_message(game_id, request.fromIndex)
        new_state = await service.load_game_state(game_id)
        new_messages = await service.load_chat_messages(game_id)

    return {"success": True, **result, "state": new_state, "messages": new_messages}


# =============================================================================
# CHAT ENDPOINT (STREAMING)
# =============================================================================

# Per-game locks to prevent concurrent _handle_chat for the same game
_game_locks: dict[str, asyncio.Lock] = {}


def _get_game_lock(game_id: UUID) -> asyncio.Lock:
    key = str(game_id)
    if key not in _game_locks:
        _game_locks[key] = asyncio.Lock()
    return _game_locks[key]


@router.post("/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_settings_dep),
):
    """Main chat endpoint with SSE streaming (with ownership check)."""
    # Verify ownership before starting the stream
    service = GameService(pool)
    await service.verify_ownership(request.gameId, user["id"])

    # Reject if another request is already processing this game
    lock = _get_game_lock(request.gameId)
    if lock.locked():
        sse_writer = SSEWriter()
        asyncio.create_task(_reject_busy(sse_writer))
        return create_sse_response(sse_writer)

    sse_writer = SSEWriter()

    asyncio.create_task(
        _handle_chat_locked(
            lock=lock,
            request=request,
            sse_writer=sse_writer,
            pool=pool,
            settings=settings,
            background_tasks=background_tasks,
            user_id=user["id"],
        )
    )

    return create_sse_response(sse_writer)


async def _reject_busy(sse_writer: SSEWriter):
    """Send error and close for busy game."""
    await sse_writer.send_error(
        "A request is already being processed for this game.",
        recoverable=True,
    )
    await sse_writer.close()


async def _handle_chat_locked(lock: asyncio.Lock, **kwargs):
    """Acquire game lock then delegate to _handle_chat."""
    async with lock:
        await _handle_chat(**kwargs)


async def _handle_chat(
    request: ChatRequest,
    sse_writer: SSEWriter,
    pool: asyncpg.Pool,
    settings: Settings,
    background_tasks: BackgroundTasks,
    user_id: UUID | None = None,
):
    """Gère le traitement du chat de manière asynchrone"""
    try:
        game_service = GameService(pool)
        llm_service = get_llm_service()

        game_id = request.gameId
        message = request.message

        # =====================================================================
        # CHARGER L'ÉTAT DEPUIS LA DB (via GameService)
        # =====================================================================
        server_state = await game_service.load_game_state(game_id)

        is_init_mode = not server_state.get("world_created", False)

        # Resolve provider: use request.provider + user's encrypted API key
        provider_name = request.provider or "anthropic"
        user_api_key = None
        if user_id:
            try:
                user_api_key = await _resolve_user_api_key(pool, user_id, provider_name)
            except Exception as e:
                logger.warning(f"[CHAT] Failed to resolve user API key: {e}")

        if not user_api_key:
            await sse_writer.send_error(
                f"Aucune clé API configurée pour {provider_name}. "
                "Ajoutez votre clé dans Paramètres > Modèle IA.",
                recoverable=False,
            )
            return

        game_session = server_state.get("game", {})
        current_cycle = game_session.get("current_cycle", 1)
        current_time = game_session.get("time", "08h00")
        current_location = game_session.get("current_location", "")

        # Engine setup
        engine_type = game_session.get("engine", "none")
        engine = get_engine(engine_type)

        is_first_light = server_state.get("world_created") and not current_location

        # =====================================================================
        # MODE INIT (World Builder)
        # =====================================================================
        if is_init_mode:
            logger.info("[CHAT] Mode: INIT (World Builder)")

            # Use engine from request (wizard) or fallback to game_session
            init_engine = request.engine or engine_type
            init_world_config = request.world_config
            init_character_data = request.character_data
            init_manual_entities = request.manual_entities

            # Extract manual NPCs as mandatory_npcs if provided
            mandatory_npcs = None
            if init_manual_entities and "npcs" in init_manual_entities:
                mandatory_npcs = init_manual_entities["npcs"]

            # Load genre from DB (from game or world_config)
            genre = None
            genre_id = game_session.get("genre_id")
            if not genre_id and init_world_config:
                # Genre slug might be in world_config from wizard
                genre_slug = init_world_config.get("genre")
                if genre_slug:
                    async with pool.acquire() as conn:
                        genre_row = await conn.fetchrow(
                            "SELECT * FROM genres WHERE slug = $1 LIMIT 1",
                            genre_slug,
                        )
                        if genre_row:
                            genre = dict(genre_row)
                            # Store genre_id on game for future use
                            await conn.execute(
                                "UPDATE games SET genre_id = $1 WHERE id = $2",
                                genre_row["id"], game_id,
                            )
            elif genre_id:
                from kg.reader import KnowledgeGraphReader
                reader = KnowledgeGraphReader(pool, game_id)
                async with pool.acquire() as conn:
                    genre = await reader.get_genre(conn, genre_id)

            # Protagonist name from character_data or default
            protagonist_name = "Valentin"
            if init_character_data and init_character_data.get("name"):
                protagonist_name = init_character_data["name"]

            prompt = get_full_generation_prompt(
                protagonist_name=protagonist_name,
                mandatory_npcs=mandatory_npcs,
                theme_preferences=message
                if message and not message.startswith("__")
                else None,
                employer_preference="employed",
                engine=init_engine,
                world_config=init_world_config,
                character_data=init_character_data,
                manual_entities=init_manual_entities,
                genre=genre,
            )

            async def on_init_complete(parsed, display_text, raw_json):
                logger.debug(f"[DEBUG] raw_json length: {len(raw_json)}")
                logger.debug(f"[DEBUG] raw_json ends with: ...{raw_json[-100:]}")
                if not parsed:
                    await sse_writer.send_error(
                        "Échec de génération du monde",
                        recoverable=True,
                        details={
                            "raw_length": len(raw_json),
                            "last_100": raw_json[-100:],
                        },
                    )
                    return

                try:
                    world_gen = WorldGeneration.model_validate(parsed)
                    init_result = await game_service.process_init(game_id, world_gen)

                    # Set engine + world_config and create engine character
                    if init_engine and init_engine != "none":
                        async with pool.acquire() as eng_conn:
                            populator = game_service._get_populator(game_id)
                            await populator.set_engine(
                                eng_conn, init_engine, init_world_config
                            )
                            eng = get_engine(init_engine)
                            await eng.create_character(
                                eng_conn, game_id,
                                init_character_data or {},
                            )

                    # Load canonical state (same shape as light mode)
                    state = await game_service.load_game_state(game_id)

                    init_cost = getattr(llm_service, "_last_call_cost", None)
                    payload = SSEDonePayload(
                        game_state=SSEGameState(
                            game=state["game"],
                            player=state["player"],
                            ai=state.get("ai"),
                            world_created=True,
                            engine=init_engine if init_engine != "none" else None,
                            engine_stats=state["player"].get("engine_stats"),
                        ),
                        world_info=WorldInfo(
                            world=WorldSummary(**init_result["world"]),
                            protagonist=ProtagonistSummary(
                                **init_result["protagonist"]
                            ),
                            ai=AISummary(**init_result["ai"]),
                            npc_count=init_result["npc_count"],
                            location_count=init_result["location_count"],
                            org_count=init_result["org_count"],
                            inventory_count=init_result["inventory_count"],
                            arrival=ArrivalSummary(**init_result["arrival"])
                            if init_result.get("arrival")
                            else None,
                            arrival_event=parsed.get("arrival_event"),
                        ),
                        meta=SSEMeta(narration_cost=init_cost)
                        if init_cost
                        else None,
                    )

                    # Store game_duration from wizard config
                    init_game_duration = (init_world_config or {}).get("duration", "medium")
                    async with pool.acquire() as dir_conn:
                        await dir_conn.execute(
                            "UPDATE games SET game_duration = $2 WHERE id = $1",
                            game_id, init_game_duration,
                        )

                    # Initial Director run (blocking, streamed to frontend)
                    try:
                        from services.director_service import run_director as run_director_init
                        await asyncio.wait_for(
                            run_director_init(
                                pool=pool,
                                game_id=game_id,
                                current_cycle=1,
                                current_time="08h00",
                                provider_name=provider_name,
                                api_key=user_api_key,
                                sse_writer=sse_writer,
                            ),
                            timeout=30.0,
                        )
                        logger.info("[CHAT] Initial Director run completed")
                    except (asyncio.TimeoutError, Exception) as dir_err:
                        logger.warning(f"[DIRECTOR] Initial run failed/timeout: {dir_err}")

                    await sse_writer.send_done(
                        None, payload.model_dump(exclude_none=True)
                    )
                    await sse_writer.send_saved()

                except Exception as e:
                    logger.error(f"[CHAT] Error process init: {e}", exc_info=True)
                    await sse_writer.send_error(str(e), recoverable=True)

            await llm_service.stream_narration(
                system_prompt=prompt["system"],
                messages=[{"role": "user", "content": prompt["user"]}],
                sse_writer=sse_writer,
                is_init_mode=True,
                temperature=1.0,
                on_complete=on_init_complete,
                provider_name=provider_name,
                api_key=user_api_key,
                model=request.model,
            )

        # =====================================================================
        # MODE LIGHT (Narration)
        # =====================================================================
        else:
            mode_label = "FIRST_LIGHT" if is_first_light else "LIGHT"
            logger.info(f"[CHAT] Mode: {mode_label}, Cycle: {current_cycle}")

            # Si first_light, utiliser l'événement d'arrivée comme contexte initial
            if is_first_light and message.startswith("__"):
                # Genre-aware arrival prompt
                genre_arrival = None
                genre_id = game_session.get("genre_id")
                if genre_id:
                    from kg.reader import KnowledgeGraphReader
                    reader = KnowledgeGraphReader(pool, game_id)
                    async with pool.acquire() as conn:
                        g = await reader.get_genre(conn, genre_id)
                        if g and g.get("arrival_prompt"):
                            world_name = game_session.get("world_name", "")
                            genre_arrival = g["arrival_prompt"].replace(
                                "{world_name}", world_name
                            ).replace(
                                "{protagonist_name}", game_session.get("protagonist_name", "")
                            )
                message = genre_arrival or "Je viens d'arriver. Mon IA personnelle commente."

            async with pool.acquire() as conn:
                builder = ContextBuilder(pool, game_id)
                context = await builder.build(
                    conn=conn,
                    player_input=message,
                    current_cycle=current_cycle,
                    current_time=current_time,
                    current_location_name=current_location,
                )

            # Run mechanical step (fate_core/d6 only)
            # If resuming from aspect invocation, use stored roll
            mechanical_result = None
            if request.roll_id:
                # Resume from Fate Core aspect invocation
                pending = await game_service.load_pending_roll(
                    game_id, request.roll_id
                )
                if not pending:
                    await sse_writer.send_error(
                        "Pending roll not found", recoverable=True
                    )
                    await sse_writer.close()
                    return

                roll_data = dict(pending["roll_details"])
                invoked = request.invoked_aspects or []

                if invoked:
                    # Apply +2 per invoked aspect
                    bonus = len(invoked) * 2
                    roll_data["skill_total"] = roll_data["skill_total"] + bonus
                    difficulty = roll_data.get("details", {}).get("difficulty", 0)
                    new_shifts = roll_data["skill_total"] - difficulty
                    if new_shifts < 0:
                        roll_data["outcome"] = "failure"
                    elif new_shifts == 0:
                        roll_data["outcome"] = "tie"
                    elif new_shifts >= 3:
                        roll_data["outcome"] = "success_with_style"
                    else:
                        roll_data["outcome"] = "success"
                    roll_data["shifts"] = new_shifts
                    roll_data.setdefault("details", {})
                    roll_data["details"]["invoked_aspects"] = invoked
                    roll_data["details"]["invocation_bonus"] = bonus
                    roll_data["details"]["fate_points_spent"] = len(invoked)

                updated_roll = RollResult(**roll_data)
                mechanical_result = MechanicalResult(
                    decision=MechanicalDecision(
                        requires_test=True,
                        skill=roll_data.get("details", {}).get("skill_name"),
                        skill_value=roll_data.get("details", {}).get("skill_value"),
                        difficulty=roll_data.get("details", {}).get("difficulty"),
                    ),
                    roll=updated_roll,
                )

                # Apply roll result (stress + fate point deduction)
                async with pool.acquire() as apply_conn:
                    await engine.apply_roll_result(
                        apply_conn, game_id, updated_roll, current_cycle,
                    )
                # Update stored roll
                await game_service.update_mechanic_roll(
                    request.roll_id, roll_data, updated_roll.outcome,
                )
                await sse_writer.send_roll_result(updated_roll.model_dump())

            elif engine.needs_mechanical_step() and context.engine_stats:
                mechanical_result = await run_mechanical_step(
                    engine=engine,
                    engine_stats=context.engine_stats,
                    player_message=message,
                    context_summary="",  # TODO: build short context summary
                    world_difficulty="moderate",  # TODO: from world_config
                    llm_service=llm_service,
                    provider_name=provider_name,
                    api_key=user_api_key,
                )
                # Check if Fate Core invocation is available
                if (
                    mechanical_result
                    and mechanical_result.roll
                    and engine_type == "fate_core"
                    and mechanical_result.roll.outcome == "failure"
                ):
                    fate_points = context.engine_stats.get("fate_points", 0)
                    aspects = context.engine_stats.get("aspects", [])
                    if fate_points > 0 and aspects:
                        # Store pending roll and pause pipeline
                        roll_id = await game_service.log_mechanic_roll(
                            game_id=game_id,
                            message_id=None,
                            engine=engine_type,
                            skill_used=mechanical_result.roll.details.get("skill_name"),
                            roll_details=mechanical_result.roll.model_dump(),
                            outcome=mechanical_result.roll.outcome,
                            complication=mechanical_result.roll.complication,
                            cycle=current_cycle,
                        )
                        await sse_writer.send_roll_pending({
                            "roll_id": str(roll_id),
                            "roll": mechanical_result.roll.model_dump(),
                            "aspects": aspects,
                            "fate_points": fate_points,
                        })
                        await sse_writer.close()
                        return

                # Normal flow: apply result + send to frontend
                if mechanical_result and mechanical_result.roll:
                    async with pool.acquire() as apply_conn:
                        await engine.apply_roll_result(
                            apply_conn, game_id,
                            mechanical_result.roll, current_cycle,
                        )
                    await sse_writer.send_roll_result(
                        mechanical_result.roll.model_dump()
                    )

            # Build engine + genre-aware prompts
            system_prompt = build_narrator_system_prompt(engine_type, genre=context.genre)
            context_prompt = build_narrator_context_prompt(
                context, engine_type, mechanical_result
            )
            logger.debug(f"[CHAT] context prompt: {len(context_prompt)} chars")

            # Build multi-turn messages array (history + context prompt)
            # Wrap assistant history in JSON for providers that need it
            from services.llm_providers import get_provider
            provider = get_provider(provider_name, api_key=user_api_key)
            json_history = getattr(provider, "FORCE_JSON", False)
            llm_messages = await game_service.build_llm_messages(
                game_id, current_cycle, context_prompt,
                json_history=json_history,
            )
            logger.info(
                f"[CHAT] Multi-turn: {len(llm_messages)} messages "
                f"({len(llm_messages) - 1} history + 1 context)"
            )
            # Log full LLM context
            logger.info(f"[CHAT] === SYSTEM PROMPT ===\n{system_prompt}")
            for i, msg in enumerate(llm_messages):
                content = msg["content"]
                if isinstance(content, list):
                    content = content[0]["text"] if content else ""
                logger.info(f"[CHAT] === MESSAGE [{i}] ({msg['role']}) ===\n{content}")

            async def on_light_complete(parsed, display_text, raw_json):
                t0 = time.perf_counter()
                if not parsed:
                    await sse_writer.send_error(
                        "Échec de génération narrative", recoverable=True
                    )
                    return

                try:
                    # Fill missing required fields with current game state
                    if "time" not in parsed:
                        parsed["time"] = {"new_time": current_time, "ellipse": False}
                    if "current_location" not in parsed:
                        parsed["current_location"] = current_location

                    t1 = time.perf_counter()
                    narration = NarrationOutput.model_validate(parsed)
                    logger.debug(
                        f"[TIMING] validation: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )

                    # 1. Update game state (cycle, time, location)
                    t1 = time.perf_counter()
                    process_result = await game_service.process_light(
                        game_id, narration, current_cycle
                    )
                    logger.debug(
                        f"[TIMING] process_light: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )

                    # 2. Apply narrator deltas immediately (credits, entity reveals, compels)
                    t1 = time.perf_counter()
                    has_deltas = (
                        narration.credit_delta
                        or narration.entity_reveals
                        or narration.compel_result
                    )
                    if has_deltas:
                        delta_result = await game_service.apply_narrator_deltas(
                            game_id, narration, process_result["cycle"]
                        )
                        logger.info(
                            f"[CHAT] Deltas applied: {json.dumps(delta_result, default=str)}"
                        )
                    logger.debug(
                        f"[TIMING] apply_deltas: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )

                    # 3. Store info requests for next turn
                    if narration.info_requests:
                        await game_service.store_info_requests(
                            game_id, narration.info_requests
                        )
                        logger.info(
                            f"[CHAT] Info requests stored: {narration.info_requests}"
                        )

                    # 4. Build client state
                    t1 = time.perf_counter()
                    state = await game_service.load_game_state(game_id)
                    state["game"].update(
                        {
                            "current_cycle": process_result["cycle"],
                            "time": process_result["time"],
                            "current_location": process_result["location"],
                            "npcs_present": process_result["npcs_present"],
                        }
                    )
                    if process_result.get("date"):
                        state["game"]["game_date"] = process_result["date"]

                    logger.debug(
                        f"[TIMING] load_state: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )

                    # 5. Build structured payload
                    narration_cost = getattr(llm_service, "_last_call_cost", None)
                    mech_cost = (
                        mechanical_result.cost if mechanical_result else None
                    )
                    payload = SSEDonePayload(
                        game_state=SSEGameState(
                            game=state["game"],
                            player=state["player"],
                            ai=state.get("ai"),
                            world_created=state.get("world_created", True),
                            engine=engine_type if engine_type != "none" else None,
                            engine_stats=state["player"].get("engine_stats"),
                        ),
                        meta=SSEMeta(
                            narration_cost=narration_cost,
                            mechanical_cost=mech_cost,
                        )
                        if narration_cost or mech_cost
                        else None,
                        ui=SSEUIHints(
                            inventory_hints=[
                                h.model_dump() for h in narration.inventory_hints
                            ],
                        )
                        if narration.inventory_hints
                        else None,
                    )

                    # 6. Send done to client
                    await sse_writer.send_done(
                        display_text, payload.model_dump(exclude_none=True)
                    )

                    # 7. Save messages (with narrator deltas + extraction triggers)
                    t1 = time.perf_counter()
                    deltas_typed = NarratorDeltasStored(
                        credit_delta=narration.credit_delta.model_dump()
                        if narration.credit_delta
                        else None,
                        inventory_hints=[
                            h.model_dump() for h in narration.inventory_hints
                        ],
                        entity_reveals=[
                            r.model_dump() for r in narration.entity_reveals
                        ],
                        extraction_triggers=narration.extraction_triggers,
                        cost=narration_cost if narration_cost else None,
                    )

                    # Snapshot engine state for rollback support
                    engine_snapshot = None
                    if engine_type != "none":
                        async with pool.acquire() as snap_conn:
                            engine_snapshot = await engine.snapshot_state(
                                snap_conn, game_id
                            )

                    _, assistant_msg_id = await game_service.save_messages(
                        game_id=game_id,
                        user_message=message,
                        assistant_message=display_text,
                        cycle=process_result["cycle"],
                        time=process_result.get("time"),
                        game_date=process_result.get("date"),
                        location_ref=process_result["location"],
                        narrator_deltas=deltas_typed.model_dump(exclude_none=True),
                        engine_snapshot=engine_snapshot,
                    )
                    # Log mechanical roll with message reference
                    if mechanical_result and mechanical_result.roll:
                        if request.roll_id:
                            # Update existing pending roll with message_id
                            await game_service.update_mechanic_roll(
                                request.roll_id,
                                mechanical_result.roll.model_dump(),
                                mechanical_result.roll.outcome,
                                message_id=assistant_msg_id,
                            )
                        else:
                            await game_service.log_mechanic_roll(
                                game_id=game_id,
                                message_id=assistant_msg_id,
                                engine=engine_type,
                                skill_used=mechanical_result.roll.details.get("skill_name"),
                                roll_details=mechanical_result.roll.model_dump(),
                                outcome=mechanical_result.roll.outcome,
                                complication=mechanical_result.roll.complication,
                                cycle=process_result["cycle"],
                            )

                    logger.debug(
                        f"[TIMING] save_messages: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )
                    await sse_writer.send_saved()

                    # 8. Background: resolver (always) + extractors (if triggered)
                    extraction_triggers = getattr(narration, "extraction_triggers", [])
                    if extraction_triggers:
                        logger.info(
                            f"[CHAT] Extraction triggers: {extraction_triggers}"
                        )
                    asyncio.create_task(
                        run_resolve_and_extract(
                            pool=pool,
                            game_id=game_id,
                            trigger_cycle=current_cycle,
                            triggers=extraction_triggers or None,
                            provider_name=provider_name,
                            api_key=user_api_key,
                            assistant_message_id=assistant_msg_id,
                            message_content=display_text,
                            narrator_deltas=deltas_typed.model_dump(exclude_none=True),
                        )
                    )

                    # 9. Background: Director (if enough IG time elapsed)
                    try:
                        from services.director_service import should_run_director, run_director

                        game_for_dir = await game_service.load_game_state(game_id)
                        g = game_for_dir.get("game", {})
                        if should_run_director(
                            process_result["time"],
                            g.get("last_director_time"),
                            g.get("game_duration", "medium"),
                        ):
                            asyncio.create_task(
                                run_director(
                                    pool=pool,
                                    game_id=game_id,
                                    current_cycle=process_result["cycle"],
                                    current_time=process_result["time"],
                                    provider_name=provider_name,
                                    api_key=user_api_key,
                                )
                            )
                            logger.info(
                                f"[CHAT] Director triggered at {process_result['time']}"
                            )
                    except Exception as dir_err:
                        logger.warning(f"[DIRECTOR] Trigger check failed: {dir_err}")

                    logger.debug(
                        f"[TIMING] TOTAL on_light_complete: {(time.perf_counter() - t0) * 1000:.0f}ms"
                    )

                except Exception as e:
                    logger.error(f"[CHAT] Erreur process light: {e}")
                    import traceback

                    traceback.print_exc()
                    await sse_writer.send_error(str(e), recoverable=True)

            # Lock engine on first non-init message
            if engine_type != "none" and not game_session.get("engine_locked"):
                async with pool.acquire() as lock_conn:
                    populator = game_service._get_populator(game_id)
                    await populator.lock_engine(lock_conn)

            await llm_service.stream_narration(
                system_prompt=system_prompt,
                messages=llm_messages,
                sse_writer=sse_writer,
                is_init_mode=False,
                on_complete=on_light_complete,
                provider_name=provider_name,
                api_key=user_api_key,
                model=request.model,
            )

    except Exception as e:
        logger.debug(f"[CHAT] Erreur non gérée: {e}")
        import traceback

        traceback.print_exc()
        await sse_writer.send_error(str(e), recoverable=False)

    finally:
        await sse_writer.close()
