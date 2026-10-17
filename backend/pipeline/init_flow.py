"""World generation turn (INIT): genre, world builder stream, population, initial Director."""

import asyncio
import logging
from dataclasses import replace
from uuid import UUID

from pydantic import ValidationError

from config import get_settings
from domain.game import GameSnapshot
from pipeline import director_runs, narration_stream
from pipeline.narration_stream import NarrationStream
from pipeline.context import InitParams, TurnContext
from pipeline.errors import TurnError, finish_saved
from pipeline.uncancellable import finish_despite_cancel
from prompts.world_generation_prompt import get_full_generation_prompt
from repos import games as games_repo
from schema import WorldGeneration
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
from services.director_service import run_director
from services.engine import get_engine

logger = logging.getLogger(__name__)

DEFAULT_PROTAGONIST_NAME = "Valentin"
DIRECTOR_INIT_TIMEOUT = 30.0
WORLD_GEN_FAILED = "Échec de génération du monde. Réessaie."


async def resolve_genre(conn, snapshot: GameSnapshot, init: InitParams) -> dict | None:
    """The game's genre, else the wizard slug's genre, then stored on the game."""
    if snapshot.genre_id:
        return await games_repo.get_genre(conn, snapshot.genre_id)
    slug = (init.world_config or {}).get("genre")
    if not slug:
        return None
    genre = await games_repo.get_genre_by_slug(conn, slug)
    if genre:
        await games_repo.set_game_genre(conn, snapshot.id, genre["id"])
    return genre


def _build_prompt(message: str, init: InitParams, engine: str, genre: dict | None) -> dict:
    manual = init.manual_entities
    character = init.character_data
    return get_full_generation_prompt(
        protagonist_name=(character or {}).get("name") or DEFAULT_PROTAGONIST_NAME,
        mandatory_npcs=manual["npcs"] if manual and "npcs" in manual else None,
        theme_preferences=message if message and not message.startswith("__") else None,
        employer_preference="employed",
        engine=engine,
        world_config=init.world_config,
        character_data=character,
        manual_entities=manual,
        genre=genre,
    )


def build_world_payload(client_state: dict, init_result: dict, init: InitParams,
                        parsed: dict, cost: dict | None) -> SSEDonePayload:
    """Done payload of the world generation turn (pure)."""
    arrival = init_result.get("arrival")
    return SSEDonePayload(
        game_state=SSEGameState(
            game=client_state["game"],
            player=client_state["player"],
            ai=client_state.get("ai"),
            world_created=True,
            engine=init.engine if init.engine != "none" else None,
            engine_stats=client_state["player"].get("engine_stats"),
        ),
        world_info=WorldInfo(
            world=WorldSummary(**init_result["world"]),
            protagonist=ProtagonistSummary(**init_result["protagonist"]),
            ai=AISummary(**init_result["ai"]),
            npc_count=init_result["npc_count"],
            location_count=init_result["location_count"],
            org_count=init_result["org_count"],
            inventory_count=init_result["inventory_count"],
            arrival=ArrivalSummary(**arrival) if arrival else None,
            arrival_event=parsed.get("arrival_event"),
        ),
        meta=SSEMeta(narration_cost=cost) if cost else None,
    )


def _validate_world(parsed: dict | None, raw: str) -> WorldGeneration:
    if not parsed:
        logger.warning(f"[INIT] Unparsable world: length={len(raw)}")
        if get_settings().log_prompts:  # the raw output is story text
            logger.debug(f"[INIT] Unparsable world tail: {raw[-100:]!r}")
        raise TurnError("world_gen_failed", WORLD_GEN_FAILED)
    try:
        return WorldGeneration.model_validate(parsed)
    except ValidationError as exc:
        # Raw Pydantic text never reaches the player.
        raise TurnError("world_gen_failed", WORLD_GEN_FAILED) from exc


def _engine_and_duration(init: InitParams, game_id: UUID):
    """Writes done in the world save transaction: engine, world config, character, duration."""
    async def write(conn) -> None:
        if init.engine and init.engine != "none":
            await games_repo.set_engine(conn, game_id, init.engine, init.world_config)
            await get_engine(init.engine).create_character(conn, game_id,
                                                           init.character_data or {})
        await games_repo.set_game_duration(conn, game_id,
                                           (init.world_config or {}).get("duration", "medium"))
    return write


def _start_initial_director(ctx: TurnContext) -> asyncio.Task | None:
    """Initial Director as its own task: it outlives the turn when the client leaves, and
    the game's first narration turn waits for it (director_runs)."""
    return director_runs.start(ctx.request.game_id, _run_initial_director(ctx),
                               wait_limit=DIRECTOR_INIT_TIMEOUT)


async def _run_initial_director(ctx: TurnContext) -> None:
    """Initial Director run, streamed to the client; a failure is only a warning."""
    try:
        await asyncio.wait_for(
            run_director(pool=ctx.pool, game_id=ctx.request.game_id, current_cycle=1,
                         current_time="08h00", session=ctx.session, sse_writer=ctx.sink),
            timeout=DIRECTOR_INIT_TIMEOUT,
        )
        logger.info("[CHAT] Initial Director run completed")
    except (asyncio.TimeoutError, Exception) as dir_err:
        logger.warning(f"[DIRECTOR] Initial run failed/timeout: {dir_err}")


async def run_init(ctx: TurnContext) -> None:
    """Generate the world. Catches nothing: the API adapter reports failures."""
    logger.info("[CHAT] Mode: INIT (World Builder)")
    game_id = ctx.request.game_id
    base = ctx.request.init or InitParams(engine=None, world_config=None, character_data=None,
                                          manual_entities=None)
    # Engine from the wizard, else the game's engine.
    init = replace(base, engine=base.engine or ctx.snapshot.engine)

    async with ctx.pool.acquire() as conn:
        genre = await resolve_genre(conn, ctx.snapshot, init)
    prompt = _build_prompt(ctx.request.message, init, init.engine, genre)

    result = await narration_stream.stream_narration(
        ctx.session, ctx.sink, system_prompt=prompt["system"],
        messages=[{"role": "user", "content": prompt["user"]}],
        world_gen=True, temperature=1.0,
    )
    world_gen = _validate_world(result.parsed, result.raw)

    # Waiting for a connection stays cancellable; once it is held, the world save (one
    # transaction: world, engine, character, duration) and the initial Director start
    # complete even if the client leaves, COMMIT included (#20, #79).
    # Invariant: no await between acquire() and finish_despite_cancel(), which creates the
    # shielded task synchronously: that task owns `conn` and always releases it.
    conn = await ctx.pool.acquire()
    init_result, director = await finish_despite_cancel(
        _save_world(ctx, conn, init, world_gen), ref=ctx.ref)
    # A connected client sees the Director's status, then done and saved. A client gone
    # meanwhile cancels only this wait: the Director (up to 30 s) finishes in the
    # background and the game lock is released at once (#79).
    # None only if a Director already runs for this game: not expected for a game whose world
    # was just generated (nothing schedules one before), kept as a guard.
    if director is not None:
        await asyncio.shield(director)
    # Saved: a failure from here on must not invite a resend (the world would be generated
    # twice).
    await finish_saved(_send_world_done(ctx, init, init_result, result), ref=ctx.ref,
                       world=True)


async def _save_world(ctx: TurnContext, conn, init: InitParams,
                      world_gen: WorldGeneration) -> tuple[dict, asyncio.Task | None]:
    """Save the world on `conn` (then released), then start its initial Director."""
    game_id = ctx.request.game_id
    try:
        init_result = await ctx.games.process_init(
            game_id, world_gen, finalize=_engine_and_duration(init, game_id), conn=conn)
    finally:
        await ctx.pool.release(conn)
    return init_result, _start_initial_director(ctx)


async def _send_world_done(ctx: TurnContext, init: InitParams, init_result: dict,
                           result: NarrationStream) -> None:
    """Done payload from the saved state, then done and saved."""
    state = await ctx.games.load_game_state(ctx.request.game_id)
    payload = build_world_payload(state, init_result, init, result.parsed, result.cost)
    await ctx.sink.send_done(None, payload.model_dump(exclude_none=True), world=True)
    await ctx.sink.send_saved()
