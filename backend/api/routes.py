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
from fastapi import APIRouter, BackgroundTasks, Depends
from prompts.narrator_prompt import (
    NARRATOR_SYSTEM_PROMPT,
    build_narrator_context_prompt,
)
from pydantic import BaseModel
from schema import NarrationOutput, WorldGeneration
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
from services.extraction_service import run_batch_extraction
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


@router.post("/games")
async def create_game(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Create a new game for the current user."""
    service = GameService(pool)
    game_id = await service.create_game(user["id"])
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

        is_first_light = server_state.get("world_created") and not current_location

        # =====================================================================
        # MODE INIT (World Builder)
        # =====================================================================
        if is_init_mode:
            logger.info("[CHAT] Mode: INIT (World Builder)")

            ### TODO un jour, il faudra ajouter la paramétrisation du npc soi même mandatory en config avant création du monde. Idem pour lieu, station ?
            prompt = get_full_generation_prompt(
                mandatory_npcs=None,  # À paramétrer selon besoin
                theme_preferences=message
                if message and not message.startswith("__")
                else None,
                employer_preference="employed",
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

                    # Load canonical state (same shape as light mode)
                    state = await game_service.load_game_state(game_id)

                    payload = SSEDonePayload(
                        game_state=SSEGameState(
                            game=state["game"],
                            player=state["player"],
                            ai=state.get("ai"),
                            world_created=True,
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
                    )

                    await sse_writer.send_done(
                        None, payload.model_dump(exclude_none=True)
                    )
                    await sse_writer.send_saved()

                except Exception as e:
                    logger.error(f"[CHAT] Error process init: {e}")
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
            if is_first_light:
                message = (
                    message
                    if not message.startswith("__")
                    else "Je viens d'arriver sur la station. IA (remplacer par personnal_ai.name) commente."
                )

            async with pool.acquire() as conn:
                builder = ContextBuilder(pool, game_id)
                context = await builder.build(
                    conn=conn,
                    player_input=message,
                    current_cycle=current_cycle,
                    current_time=current_time,
                    current_location_name=current_location,
                )

            context_prompt = build_narrator_context_prompt(context)
            logger.info(f"[CHAT] prompt: \n{context_prompt}")

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
            logger.info(f"[CHAT] === SYSTEM PROMPT ===\n{NARRATOR_SYSTEM_PROMPT}")
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
                    t1 = time.perf_counter()
                    narration = NarrationOutput.model_validate(parsed)
                    logger.debug(
                        f"[TIMING] validation: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )

                    # Clamp suggested_actions to 5 max
                    if len(narration.suggested_actions) > 5:
                        narration.suggested_actions = narration.suggested_actions[:5]

                    # 1. Update game state (cycle, time, location)
                    t1 = time.perf_counter()
                    process_result = await game_service.process_light(
                        game_id, narration, current_cycle
                    )
                    logger.debug(
                        f"[TIMING] process_light: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )

                    # 2. Apply narrator deltas immediately (gauges, credits)
                    t1 = time.perf_counter()
                    if (
                        narration.gauge_deltas
                        or narration.credit_delta
                        or narration.entity_reveals
                    ):
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
                    payload = SSEDonePayload(
                        game_state=SSEGameState(
                            game=state["game"],
                            player=state["player"],
                            ai=state.get("ai"),
                            world_created=state.get("world_created", True),
                        ),
                        meta=SSEMeta(narration_cost=narration_cost)
                        if narration_cost
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

                    # 7. Save messages (with narrator deltas + hints for batch extraction)
                    t1 = time.perf_counter()
                    deltas_typed = NarratorDeltasStored(
                        gauge_deltas=[g.model_dump() for g in narration.gauge_deltas],
                        credit_delta=narration.credit_delta.model_dump()
                        if narration.credit_delta
                        else None,
                        inventory_hints=[
                            h.model_dump() for h in narration.inventory_hints
                        ],
                        entity_reveals=[
                            r.model_dump() for r in narration.entity_reveals
                        ],
                        hints=narration.hints.model_dump() if narration.hints else None,
                        cost=narration_cost if narration_cost else None,
                    )
                    await game_service.save_messages(
                        game_id=game_id,
                        user_message=message,
                        assistant_message=display_text,
                        cycle=process_result["cycle"],
                        time=process_result.get("time"),
                        game_date=process_result.get("date"),
                        location_ref=process_result["location"],
                        narrator_deltas=deltas_typed.model_dump(exclude_none=True),
                    )
                    logger.debug(
                        f"[TIMING] save_messages: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )
                    await sse_writer.send_saved()

                    # 8. Trigger batch extraction (day transition or time interval)
                    # User preference overrides server default
                    extraction_interval = settings.extraction_interval_hours
                    if user_id:
                        try:
                            async with pool.acquire() as pref_conn:
                                prefs_raw = await pref_conn.fetchval(
                                    "SELECT preferences FROM users WHERE id = $1", user_id
                                )
                            if prefs_raw:
                                prefs = prefs_raw if isinstance(prefs_raw, dict) else json.loads(prefs_raw)
                                extraction_interval = prefs.get(
                                    "extraction_interval_hours", extraction_interval
                                )
                        except Exception:
                            pass  # Fall back to server default

                    should_extract = False
                    if narration.day_transition:
                        should_extract = True
                        logger.info(
                            f"[CHAT] Day transition detected, triggering batch extraction"
                        )
                    elif extraction_interval > 0:
                        from utils.time_utils import game_hours_elapsed

                        last_ext_time = game_session.get("last_extraction_time") or "00h00"
                        new_time = process_result.get("time", "")
                        elapsed = game_hours_elapsed(last_ext_time, new_time)
                        if elapsed >= extraction_interval:
                            should_extract = True
                            logger.info(
                                f"[CHAT] Time-based extraction: {elapsed:.1f}h elapsed "
                                f"(threshold: {extraction_interval}h)"
                            )

                    if should_extract:
                        if narration.day_transition:
                            # Reset for new day
                            async with pool.acquire() as ext_conn:
                                await ext_conn.execute(
                                    "UPDATE games SET last_extraction_time=NULL WHERE id=$1",
                                    game_id,
                                )
                        asyncio.create_task(
                            run_batch_extraction(
                                pool,
                                game_id,
                                current_cycle,
                                provider_name,
                                user_api_key,
                            )
                        )

                    logger.debug(
                        f"[TIMING] TOTAL on_light_complete: {(time.perf_counter() - t0) * 1000:.0f}ms"
                    )

                except Exception as e:
                    logger.error(f"[CHAT] Erreur process light: {e}")
                    import traceback

                    traceback.print_exc()
                    await sse_writer.send_error(str(e), recoverable=True)

            await llm_service.stream_narration(
                system_prompt=NARRATOR_SYSTEM_PROMPT,
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
