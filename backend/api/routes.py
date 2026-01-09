"""
LDVELH - API Routes
Routes FastAPI principales
"""

import asyncio
from uuid import UUID

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from utils import normalize_world_generation, normalize_narration_output
from prompts.narrator_prompt import (
    NARRATOR_SYSTEM_PROMPT,
    build_narrator_context_prompt,
)
from pydantic import BaseModel
from schema import NarrationOutput, WorldGeneration

from api.dependencies import get_pool, get_settings_dep
from api.streaming import SSEWriter, create_sse_response
from config import Settings
from prompts.world_generation_prompt import get_full_generation_prompt
from services.extraction_service import run_extraction_background
from services.game_service import GameService
from services.llm_service import get_llm_service

router = APIRouter()


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class GameState(BaseModel):
    """État du jeu côté client"""

    partie: dict | None = None
    valentin: dict | None = None
    ia: dict | None = None
    monde_cree: bool = False


class ChatRequest(BaseModel):
    """Requête de chat"""

    message: str
    gameId: UUID
    gameState: GameState | None = None


class RollbackRequest(BaseModel):
    """Requête de rollback"""

    gameId: UUID
    fromIndex: int


class RenameRequest(BaseModel):
    """Requête de renommage"""

    gameId: UUID
    name: str


# =============================================================================
# GET ENDPOINTS
# =============================================================================


@router.get("/games")
async def list_games(pool: asyncpg.Pool = Depends(get_pool)):
    """Liste les parties actives"""
    service = GameService(pool)
    games = await service.list_games()
    return {"parties": games}


@router.get("/games/{game_id}")
async def load_game(game_id: UUID, pool: asyncpg.Pool = Depends(get_pool)):
    """Charge une partie"""
    service = GameService(pool)

    try:
        state = await service.load_game_state(game_id)
        messages = await service.load_chat_messages(game_id)
        return {"state": state, "messages": messages}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/games")
async def create_game(pool: asyncpg.Pool = Depends(get_pool)):
    """Crée une nouvelle partie"""
    service = GameService(pool)
    game_id = await service.create_game()
    return {"gameId": str(game_id)}


@router.delete("/games/{game_id}")
async def delete_game(game_id: UUID, pool: asyncpg.Pool = Depends(get_pool)):
    """Supprime une partie"""
    service = GameService(pool)
    await service.delete_game(game_id)
    return {"success": True}


@router.patch("/games/{game_id}")
async def rename_game(
    game_id: UUID, request: RenameRequest, pool: asyncpg.Pool = Depends(get_pool)
):
    """Renomme une partie"""
    service = GameService(pool)
    await service.rename_game(game_id, request.name)
    return {"success": True}


# =============================================================================
# ROLLBACK ENDPOINT
# =============================================================================


@router.post("/games/{game_id}/rollback")
async def rollback_game(
    game_id: UUID, request: RollbackRequest, pool: asyncpg.Pool = Depends(get_pool)
):
    """Rollback à un message spécifique"""
    service = GameService(pool)
    result = await service.rollback_to_message(game_id, request.fromIndex)

    # Recharger l'état
    new_state = await service.load_game_state(game_id)

    return {"success": True, **result, "state": new_state}


# =============================================================================
# CHAT ENDPOINT (STREAMING)
# =============================================================================


@router.post("/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_settings_dep),
):
    """
    Endpoint principal de chat avec streaming SSE.

    Modes:
    - INIT: Génération du monde (pas de narratif)
    - FIRST_LIGHT: Premier narratif après création du monde
    - LIGHT: Narratif normal
    """
    sse_writer = SSEWriter()

    # Lancer le traitement en background
    asyncio.create_task(
        _handle_chat(
            request=request,
            sse_writer=sse_writer,
            pool=pool,
            settings=settings,
            background_tasks=background_tasks,
        )
    )

    return create_sse_response(sse_writer)


async def _handle_chat(
    request: ChatRequest,
    sse_writer: SSEWriter,
    pool: asyncpg.Pool,
    settings: Settings,
    background_tasks: BackgroundTasks,
):
    """Gère le traitement du chat de manière asynchrone"""
    try:
        game_service = GameService(pool)
        llm_service = get_llm_service()

        game_id = request.gameId
        message = request.message
        game_state = request.gameState

        # Déterminer le mode
        is_init_mode = not game_state or not game_state.monde_cree
        is_first_light = (
            game_state
            and game_state.monde_cree
            and game_state.partie
            and not game_state.partie.get("lieu_actuel")
        )

        current_cycle = (
            game_state.partie.get("cycle_actuel", 1)
            if game_state and game_state.partie
            else 1
        )

        # =====================================================================
        # MODE INIT (World Builder)
        # =====================================================================
        if is_init_mode:
            print("[CHAT] Mode: INIT (World Builder)")

            prompt = get_full_generation_prompt(
                mandatory_npcs=None,  # À paramétrer selon besoin
                theme_preferences=message
                if message and not message.startswith("__")
                else None,
                employer_preference="employed",
            )

            async def on_init_complete(parsed, display_text, raw_json):
                print(f"[DEBUG] raw_json length: {len(raw_json)}")
                print(f"[DEBUG] raw_json ends with: ...{raw_json[-100:]}")
                print(f"[DEBUG] parsed is None: {parsed is None}")
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
                    # Normaliser AVANT validation Pydantic
                    parsed = normalize_world_generation(parsed)
                    # Valider avec Pydantic
                    world_gen = WorldGeneration.model_validate(parsed)

                    # Peupler le KG
                    init_result = await game_service.process_init(game_id, world_gen)

                    # Charger l'inventaire
                    state = await game_service.load_game_state(game_id)

                    await sse_writer.send_done(
                        None,
                        {
                            "monde_cree": True,
                            **init_result,
                            "inventaire": state["valentin"]["inventaire"],
                            "evenement_arrivee": parsed.get("arrival_event"),
                        },
                    )
                    await sse_writer.send_saved()

                except Exception as e:
                    print(f"[CHAT] Erreur process init: {e}")
                    await sse_writer.send_error(str(e), recoverable=True)

            await llm_service.stream_narration(
                system_prompt=prompt["system"],
                user_message=prompt["user"],
                sse_writer=sse_writer,
                is_init_mode=True,
                on_complete=on_init_complete,
            )

        # =====================================================================
        # MODE LIGHT (Narration)
        # =====================================================================
        else:
            mode_label = "FIRST_LIGHT" if is_first_light else "LIGHT"
            print(f"[CHAT] Mode: {mode_label}, Cycle: {current_cycle}")

            # Construire le contexte
            current_time = (
                game_state.partie.get("heure", "08h00")
                if game_state.partie
                else "08h00"
            )
            current_location = (
                game_state.partie.get("lieu_actuel", "") if game_state.partie else ""
            )

            # Si first_light, utiliser l'événement d'arrivée comme contexte initial
            if is_first_light:
                # Récupérer les infos d'arrivée depuis la BDD
                async with pool.acquire() as conn:
                    arrival_info = await conn.fetchrow(
                        """SELECT key_events FROM cycle_summaries 
                           WHERE game_id = $1 AND cycle = 1""",
                        game_id,
                    )

                if arrival_info and arrival_info["key_events"]:
                    import json

                    events = (
                        json.loads(arrival_info["key_events"])
                        if isinstance(arrival_info["key_events"], str)
                        else arrival_info["key_events"]
                    )
                    current_location = events.get("arrival_location", current_location)
                    message = message or "Je viens d'arriver sur la station."

            context = await game_service.build_narration_context(
                game_id=game_id,
                player_input=message,
                current_cycle=current_cycle,
                current_time=current_time,
                current_location=current_location,
            )

            context_prompt = build_narrator_context_prompt(context)

            async def on_light_complete(parsed, display_text, raw_json):
                if not parsed:
                    await sse_writer.send_error(
                        "Échec de génération narrative", recoverable=True
                    )
                    return

                try:
                    # Normaliser AVANT validation Pydantic
                    parsed = normalize_narration_output(parsed)
                    # Valider avec Pydantic
                    narration = NarrationOutput.model_validate(parsed)

                    # Traiter la narration
                    process_result = await game_service.process_light(
                        game_id, narration, current_cycle
                    )

                    # Construire l'état pour le client
                    state = await game_service.load_game_state(game_id)
                    state["partie"].update(
                        {
                            "cycle_actuel": process_result["cycle"],
                            "heure": process_result["time"],
                            "lieu_actuel": process_result["location"],
                            "pnjs_presents": process_result["npcs_present"],
                        }
                    )
                    if process_result.get("day"):
                        state["partie"]["jour"] = process_result["day"]
                    if process_result.get("date"):
                        state["partie"]["date_jeu"] = process_result["date"]

                    await sse_writer.send_done(display_text, state)

                    # Sauvegarder les messages
                    await game_service.save_messages(
                        game_id=game_id,
                        user_message=message,
                        assistant_message=display_text,
                        cycle=process_result["cycle"],
                        state_snapshot=process_result["state_snapshot"],
                    )

                    await sse_writer.send_saved()

                    # Lancer l'extraction en background
                    background_tasks.add_task(
                        run_extraction_background,
                        pool,
                        game_id,
                        narration.narrative_text,
                        narration.hints,
                        process_result["cycle"],
                        process_result["location"],
                        process_result["npcs_present"],
                    )

                except Exception as e:
                    print(f"[CHAT] Erreur process light: {e}")
                    import traceback

                    traceback.print_exc()
                    await sse_writer.send_error(str(e), recoverable=True)

            await llm_service.stream_narration(
                system_prompt=NARRATOR_SYSTEM_PROMPT,
                user_message=context_prompt,
                sse_writer=sse_writer,
                is_init_mode=False,
                on_complete=on_light_complete,
            )

    except Exception as e:
        print(f"[CHAT] Erreur non gérée: {e}")
        import traceback

        traceback.print_exc()
        await sse_writer.send_error(str(e), recoverable=False)

    finally:
        await sse_writer.close()
