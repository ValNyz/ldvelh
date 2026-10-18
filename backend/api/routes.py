"""
LDVELH - API Routes
Routes FastAPI principales
"""

import logging
import asyncio
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from services.engine import get_engine

from api.dependencies import get_pool, get_settings_dep, get_current_user
from api import game_writers
from api.streaming import SSEWriter, create_sse_response
from config import Settings
from llm.session import LLMSession
from repos import games as games_repo
from repos import users as users_repo
from repos.llm_models import load_catalog
from schema import PROTAGONIST_REF, is_usable_protagonist_name
from services.game_service import GameService, RollbackRejected
from pipeline import init_flow, turn
from pipeline.context import InitParams, TurnContext, TurnRequest
from pipeline.errors import TurnError, report_error
from utils.rate_limit import hit_all, request_ip, shared_limiter

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


INVALID_PC_NAME = (
    "Nom du protagoniste invalide : les caractères < et > et le nom "
    f"« {PROTAGONIST_REF} » sont réservés."
)


def _reject_unusable_wizard_name(character_data: dict | None) -> None:
    """A typed PC name must be usable (#28); blank is fine, the world builder invents one."""
    name = (character_data or {}).get("name")
    if isinstance(name, str) and name.strip() and not is_usable_protagonist_name(name):
        raise HTTPException(status_code=400, detail=INVALID_PC_NAME)


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
    """Requête de renommage (the game id is the path parameter only)"""

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
    """Return accumulated token usage and cost for the requesting user."""
    from llm.usage import get_usage_ledger

    return get_usage_ledger().get_summary(user["id"])


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


# Player text per RollbackRejected.reason: the exception text never reaches the player (#80).
ROLLBACK_REJECTED_MESSAGES = {
    RollbackRejected.ARRIVAL_SCENE: "Impossible de revenir avant la scène d'arrivée.",
}
ROLLBACK_REJECTED_DEFAULT = "Ce retour en arrière est impossible."


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
            detail = ROLLBACK_REJECTED_MESSAGES.get(e.reason, ROLLBACK_REJECTED_DEFAULT)
            raise HTTPException(status_code=400, detail=detail) from e
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


# Each turn costs LLM calls (#82): per player, and per client IP across accounts.
chat_user_limiter = shared_limiter(max_requests=10, window_seconds=60)
chat_ip_limiter = shared_limiter(max_requests=30, window_seconds=60)


@router.post("/chat")
async def chat(
    request: ChatRequest,
    raw_request: Request,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_settings_dep),
):
    """Main chat endpoint with SSE streaming (with ownership check)."""
    # Both or neither: a refusal by one limit does not use a slot of the other.
    hit_all((chat_user_limiter, f"user:{user['id']}"), (chat_ip_limiter, request_ip(raw_request)))
    _reject_unusable_wizard_name(request.character_data)
    # Verify ownership before starting the stream
    service = GameService(pool)
    await service.verify_ownership(request.gameId, user["id"])

    return create_sse_response(start_chat(request, pool, settings, user["id"]))


def start_chat(request: ChatRequest, pool: asyncpg.Pool, settings: Settings,
               user_id: UUID) -> SSEWriter:
    """Start the turn task (or the busy-game rejection) and attach it to a new writer.

    Closing the stream cancels the task: nothing is committed and the game lock is
    released when `async with lock` unwinds (#20).
    """
    writer = SSEWriter()
    key = str(request.gameId)
    lock = _get_game_lock(request.gameId)
    if game_writers.is_busy(key, lock):  # C-13
        writer.attach(asyncio.create_task(_reject_busy(writer)))
        return writer
    task = asyncio.create_task(
        _handle_chat_locked(
            lock=lock,
            request=request,
            sink=writer,
            pool=pool,
            settings=settings,
            user_id=user_id,
        )
    )
    # Registered before the task runs, removed when it is done, even if cancelled first.
    game_writers.register(key, writer, task)
    writer.attach(task)
    return writer


GAME_BUSY = "Une action est déjà en cours pour cette partie. Attends la fin du tour, puis réessaie."


async def _reject_busy(sse_writer: SSEWriter):
    """Busy game (C-13): one French error through the normal error path, then close (#80)."""
    try:
        await report_error(sse_writer, TurnError("game_busy", GAME_BUSY), provider_name=None,
                           ref=sse_writer.stream_id)
    finally:
        await sse_writer.close()


async def _handle_chat_locked(lock: asyncio.Lock, **kwargs):
    """Acquire game lock then delegate to _handle_chat."""
    async with lock:
        await _handle_chat(**kwargs)


async def _api_key_or_raise(pool: asyncpg.Pool, user_id: UUID, provider_name: str) -> str:
    """The user's API key for the provider; none ⇒ non-recoverable TurnError (C-14)."""
    user_api_key = None
    try:
        user_api_key = await _resolve_user_api_key(pool, user_id, provider_name)
    except Exception as e:
        logger.warning(f"[CHAT] Failed to resolve user API key: {e}")
    if not user_api_key:
        raise TurnError(
            "no_api_key",
            f"Aucune clé API configurée pour {provider_name}. "
            "Ajoutez votre clé dans Paramètres > Modèle IA.",
            recoverable=False,
        )
    return user_api_key


def _turn_request(request: ChatRequest, user_id: UUID) -> TurnRequest:
    return TurnRequest(
        game_id=request.gameId,
        user_id=user_id,
        message=request.message,
        roll_id=request.roll_id,
        invoked_aspects=tuple(request.invoked_aspects or ()),
        init=InitParams(
            engine=request.engine,
            world_config=request.world_config,
            character_data=request.character_data,
            manual_entities=request.manual_entities,
        ),
    )


async def _handle_chat(
    request: ChatRequest,
    sink: SSEWriter,
    pool: asyncpg.Pool,
    settings: Settings,
    user_id: UUID,
) -> None:
    """Thin adapter: snapshot, API key, session, then the init or narration pipeline."""
    provider_name = request.provider or "anthropic"
    try:
        async with pool.acquire() as conn:
            snapshot = await games_repo.get_snapshot(conn, request.gameId)
        if snapshot is None:
            raise TurnError("game_not_found", "Partie introuvable.", recoverable=False)
        api_key = await _api_key_or_raise(pool, user_id, provider_name)
        session = LLMSession(provider_name, api_key, request.model,
                             catalog=await load_catalog(pool), user_id=user_id)
        ctx = TurnContext(
            request=_turn_request(request, user_id),
            snapshot=snapshot,
            session=session,
            sink=sink,
            pool=pool,
            engine=get_engine(snapshot.engine),
            ref=sink.stream_id,
        )
        if snapshot.world_created:
            await turn.run_turn(ctx)
        else:
            await init_flow.run_init(ctx)
    except Exception as e:
        await report_error(sink, e, provider_name=provider_name, ref=sink.stream_id)
    finally:
        await sink.close()
