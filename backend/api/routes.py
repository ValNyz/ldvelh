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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
from kg.context_builder import ContextBuilder
from services.extraction_service import (
    ParallelExtractionService,
    create_summary_task,
)
from services.game_service import GameService
from services.llm_service import get_llm_service

logger = logging.getLogger(__name__)

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
    try:
        games = await service.list_games()
        return {"parties": games}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/games/{game_id}")
async def load_game(game_id: UUID, pool: asyncpg.Pool = Depends(get_pool)):
    """Charge une partie"""
    service = GameService(pool)

    try:
        state = await service.load_game_state(game_id)
        messages = await service.load_chat_messages(game_id)

        # Si le monde est créé mais pas encore de messages,
        # on charge les infos de présentation du monde
        world_info = None
        if state.get("monde_cree") and not messages:
            world_info = await service.load_world_info(game_id)

        return {
            "state": state,
            "messages": messages,
            "world_info": world_info,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/games")
async def create_game(pool: asyncpg.Pool = Depends(get_pool)):
    """Crée une nouvelle partie"""
    service = GameService(pool)
    try:
        game_id = await service.create_game()
        return {"gameId": str(game_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/games/{game_id}")
async def delete_game(game_id: UUID, pool: asyncpg.Pool = Depends(get_pool)):
    """Supprime une partie"""
    service = GameService(pool)
    try:
        await service.delete_game(game_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/games/{game_id}")
async def rename_game(
    game_id: UUID, request: RenameRequest, pool: asyncpg.Pool = Depends(get_pool)
):
    """Renomme une partie"""
    service = GameService(pool)
    try:
        await service.rename_game(game_id, request.name)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# @router.get("/games/{game_id}/world")
# async def get_world_data(game_id: UUID, pool: asyncpg.Pool = Depends(get_pool)):
#     """
#     Récupère les données du monde pour les sidebars.
#
#     Returns:
#         - npcs: Liste des PNJs connus
#         - locations: Liste des lieux découverts
#         - quests: Liste des quêtes/arcs actifs
#         - organizations: Liste des organisations connues
#     """
#     service = GameService(pool)
#     try:
#         world_data = await service.load_world_data(game_id)
#         return world_data
#     except ValueError as e:
#         raise HTTPException(status_code=404, detail=str(e))


# =============================================================================
# ROLLBACK ENDPOINT
# =============================================================================


# 2. Remplacer le endpoint rollback
@router.post("/games/{game_id}/rollback")
async def rollback_game(
    game_id: UUID, request: RollbackRequest, pool: asyncpg.Pool = Depends(get_pool)
):
    """
    Rollback à un message spécifique.

    Supprime tous les messages à partir de fromIndex (inclus)
    et rollback le Knowledge Graph au cycle correspondant.
    """
    service = GameService(pool)
    try:
        result = await service.rollback_to_message(game_id, request.fromIndex)

        # Recharger l'état et les messages
        new_state = await service.load_game_state(game_id)
        new_messages = await service.load_chat_messages(game_id)

        return {"success": True, **result, "state": new_state, "messages": new_messages}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
        extraction_service = ParallelExtractionService(pool)

        game_id = request.gameId
        message = request.message

        # =====================================================================
        # CHARGER L'ÉTAT DEPUIS LA DB (via GameService)
        # =====================================================================
        server_state = await game_service.load_game_state(game_id)

        is_init_mode = not server_state.get("monde_cree", False)

        partie = server_state.get("partie", {})
        current_cycle = partie.get("cycle_actuel", 1)
        current_time = partie.get("heure", "08h00")
        current_location = partie.get("lieu_actuel", "")

        is_first_light = server_state.get("monde_cree") and not current_location

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
                    # Normalisation et validation Pydantic
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
                    logger.error(f"[CHAT] Erreur process init: {e}")
                    await sse_writer.send_error(str(e), recoverable=True)

            await llm_service.stream_narration(
                system_prompt=prompt["system"],
                user_message=prompt["user"],
                sse_writer=sse_writer,
                is_init_mode=True,
                temperature=1.0,
                on_complete=on_init_complete,
            )

        # =====================================================================
        # MODE LIGHT (Narration)
        # =====================================================================
        else:
            mode_label = "FIRST_LIGHT" if is_first_light else "LIGHT"
            logger.info(f"[CHAT] Mode: {mode_label}, Cycle: {current_cycle}")

            # Si first_light, utiliser l'événement d'arrivée comme contexte initial
            if is_first_light:
                message = message or "Je viens d'arriver sur la station."

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
            logger.info(
                f"[CHAT] context: \n{json.dumps(context.model_dump(), indent=2, default=str, ensure_ascii=False)}"
            )

            # Variable pour stocker la tâche de résumé lancée tôt
            summary_task_holder = {"task": None}

            async def on_narrative_ready(narrative_text: str):
                """Callback dès que le narrative_text est complet"""
                logger.info("[CHAT] Narrative ready, lancement résumé anticipé")
                summary_task_holder["task"] = create_summary_task(pool, narrative_text)

            async def on_light_complete(parsed, display_text, raw_json):
                t0 = time.perf_counter()
                if not parsed:
                    await sse_writer.send_error(
                        "Échec de génération narrative", recoverable=True
                    )
                    return

                try:
                    t1 = time.perf_counter()
                    # Normalisation et validation Pydantic
                    narration = NarrationOutput.model_validate(parsed)
                    logger.debug(
                        f"[TIMING] validation + pydantic: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )
                    t1 = time.perf_counter()
                    # Traiter la narration
                    process_result = await game_service.process_light(
                        game_id, narration, current_cycle
                    )
                    logger.debug(
                        f"[TIMING] process_light: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )

                    # === EXTRACTION PARALLÈLE (BLOQUANTE) ===
                    # Signaler au client que l'extraction commence
                    # Le joueur peut taper mais pas encore envoyer
                    await sse_writer.send_extracting(display_text)

                    # Log des hints pour debug
                    hints = narration.hints
                    hints_active = []
                    if hints.new_entities_mentioned:
                        hints_active.append(f"entités:{hints.new_entities_mentioned}")
                    if hints.protagonist_state_changed:
                        hints_active.append("état_protag")
                    if hints.relationships_changed:
                        hints_active.append("relations")
                    if hints.information_learned:
                        hints_active.append("infos")
                    if hints.new_commitment_created:
                        hints_active.append("new_commit")
                    if hints.commitment_advanced:
                        hints_active.append(f"commit_adv:{hints.commitment_advanced}")
                    if hints.event_scheduled:
                        hints_active.append("event")
                    logger.debug(
                        f"[CHAT] Extraction - hints actifs: {', '.join(hints_active) or 'aucun'}"
                    )
                    t1 = time.perf_counter()
                    logger.info("[CHAT] Lancement extraction parallèle...")

                    extraction_result = await extraction_service.extract_and_populate(
                        game_id=game_id,
                        narrative_text=narration.narrative_text,
                        hints=narration.hints,
                        cycle=process_result["cycle"],
                        location=process_result["location"],
                        npcs_present=process_result["npcs_present"],
                        summary_task=summary_task_holder.get("task"),
                    )
                    logger.info(
                        f"[CHAT] Extraction terminée:\n{json.dumps(extraction_result, indent=2, default=str, ensure_ascii=False)}"
                    )
                    logger.debug(
                        f"[TIMING] extract_and_populate: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )
                    t1 = time.perf_counter()

                    # Construire l'état pour le client
                    state = await game_service.load_game_state(game_id)
                    logger.debug(
                        f"[TIMING] load_game_state: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )
                    state["partie"].update(
                        {
                            "cycle_actuel": process_result["cycle"],
                            "heure": process_result["time"],
                            "lieu_actuel": process_result["location"],
                            "pnjs_presents": process_result["npcs_present"],
                        }
                    )
                    if process_result.get("date"):
                        state["partie"]["date_jeu"] = process_result["date"]
                    t1 = time.perf_counter()
                    await sse_writer.send_done(display_text, state)

                    logger.debug(
                        f"[TIMING] send_done: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )
                    t1 = time.perf_counter()
                    # Sauvegarder les messages
                    summary_task = summary_task_holder.get("task", "")
                    segment_summary = ""
                    if summary_task and summary_task.done():
                        try:
                            summary_result = summary_task.result()
                            segment_summary = (
                                summary_result.get("segment_summary", "")
                                if summary_result
                                else ""
                            )
                        except Exception as e:
                            logger.warning(f"[CHAT] Échec récupération summary: {e}")

                    await game_service.save_messages(
                        game_id=game_id,
                        user_message=message,
                        assistant_message=display_text,
                        cycle=process_result["cycle"],
                        date=process_result.get("date"),
                        time=process_result.get("time"),
                        location_ref=process_result["location"],
                        npcs_present_refs=process_result["npcs_present"],
                        summary=segment_summary,
                    )

                    logger.debug(
                        f"[TIMING] save_messages: {(time.perf_counter() - t1) * 1000:.0f}ms"
                    )

                    await sse_writer.send_saved()

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
                user_message=context_prompt,
                sse_writer=sse_writer,
                is_init_mode=False,
                on_complete=on_light_complete,
                on_narrative_ready=on_narrative_ready,
            )

    except Exception as e:
        logger.debug(f"[CHAT] Erreur non gérée: {e}")
        import traceback

        traceback.print_exc()
        await sse_writer.send_error(str(e), recoverable=False)

    finally:
        await sse_writer.close()
