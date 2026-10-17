"""
LDVELH - API Routes
Routes FastAPI principales
"""

import logging
import asyncio
from uuid import UUID

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from pydantic import BaseModel
from schema import WorldGeneration
from services.engine import get_engine
from schema.sse_payload import (
    AISummary,
    ArrivalSummary,
    ProtagonistSummary,
    SSEDonePayload,
    SSEGameState,
    SSEMeta,
    WorldInfo,
    WorldSummary,
)

from api.dependencies import get_pool, get_settings_dep, get_current_user
from api.streaming import SSEWriter, create_sse_response
from config import Settings
from prompts.world_generation_prompt import get_full_generation_prompt
from repos import games as games_repo
from repos import users as users_repo
from repos.llm_models import load_catalog
from services.game_service import GameService, RollbackRejected
from pipeline import narration_stream, turn
from pipeline.context import TurnContext, TurnRequest
from pipeline.errors import report_error

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
        return await users_repo.get_user_api_key(conn, user_id, provider_name)


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

    messageId: str | None = None  # Preferred: UUID of the message to rollback from
    fromIndex: int | None = None  # Legacy: index-based rollback


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
    from llm.usage import get_usage_ledger

    return get_usage_ledger().get_summary()


@router.get("/providers")
async def list_providers(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List available LLM providers and their models.

    For each provider where the user has a stored API key, this fetches the
    live model list (cached per-key for 24h). Anthropic always returns its
    hardcoded model list (no live discovery endpoint). Providers with no
    user key return an empty models list so the UI can prompt for one.
    """
    from services.llm_providers import _CLASSES, get_provider_catalog_async

    user_keys: dict[str, str] = {}
    for name in _CLASSES.keys():
        key = await _resolve_user_api_key(pool, user["id"], name)
        if key:
            user_keys[name] = key
    return await get_provider_catalog_async(user_keys=user_keys, catalog=await load_catalog(pool))


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
        msg_id = UUID(request.messageId) if request.messageId else None
        try:
            result = await service.rollback_to_message(
                game_id, message_id=msg_id, keep_until_index=request.fromIndex
            )
        except RollbackRejected as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
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
    provider_name = request.provider or "anthropic"
    try:
        game_service = GameService(pool)

        game_id = request.gameId
        message = request.message

        # =====================================================================
        # CHARGER L'ÉTAT DEPUIS LA DB (via GameService)
        # =====================================================================
        from repos.games import get_snapshot

        async with pool.acquire() as snap_conn:
            snapshot = await get_snapshot(snap_conn, game_id)
        if snapshot is None:
            raise ValueError(f"Partie {game_id} introuvable")

        is_init_mode = not snapshot.world_created

        # Resolve provider: use request.provider + user's encrypted API key
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

        from llm.session import LLMSession

        session = LLMSession(provider_name, user_api_key, request.model,
                             catalog=await load_catalog(pool))

        # Engine setup
        engine_type = snapshot.engine
        engine = get_engine(engine_type)

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
            genre_id = snapshot.genre_id
            if not genre_id and init_world_config:
                # Genre slug might be in world_config from wizard
                genre_slug = init_world_config.get("genre")
                if genre_slug:
                    async with pool.acquire() as conn:
                        genre = await games_repo.get_genre_by_slug(conn, genre_slug)
                        if genre:
                            # Store genre_id on game for future use
                            await games_repo.set_game_genre(conn, game_id, genre["id"])
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

            async def on_init_complete(parsed, display_text, raw_json, cost):
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

                    init_cost = cost
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
                        await games_repo.set_game_duration(dir_conn, game_id, init_game_duration)

                    # Initial Director run (blocking, streamed to frontend)
                    try:
                        from services.director_service import run_director as run_director_init
                        await asyncio.wait_for(
                            run_director_init(
                                pool=pool,
                                game_id=game_id,
                                current_cycle=1,
                                current_time="08h00",
                                session=session,
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

            result = await narration_stream.stream_narration(
                session,
                sse_writer,
                system_prompt=prompt["system"],
                messages=[{"role": "user", "content": prompt["user"]}],
                world_gen=True,
                temperature=1.0,
            )
            await on_init_complete(
                result.parsed, result.display_text, result.raw, result.cost
            )

        # =====================================================================
        # MODE LIGHT / FIRST_LIGHT (Narration)
        # =====================================================================
        else:
            request_turn = TurnRequest(
                game_id=game_id,
                user_id=user_id,
                message=message,
                roll_id=request.roll_id,
                invoked_aspects=tuple(request.invoked_aspects or ()),
            )
            ctx = TurnContext(
                request=request_turn,
                snapshot=snapshot,
                session=session,
                sink=sse_writer,
                pool=pool,
                engine=engine,
                ref=sse_writer._stream_id,
            )
            await turn.run_turn(ctx)

    except Exception as e:
        await report_error(
            sse_writer, e, provider_name=provider_name, ref=sse_writer._stream_id
        )

    finally:
        await sse_writer.close()
