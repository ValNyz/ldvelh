"""Schedule step: post-turn job on the game's supervisor queue, Director after the turn."""

import logging

from domain.turn import TurnCommitted
from pipeline import director_runs
from pipeline.context import TurnContext
from pipeline.post_turn import run_post_turn
from pipeline.steps.commit import Committed
from pipeline.steps.narrate import Narrated
from repos.games import get_director_schedule
from services.director_service import run_director, should_run_director
from utils.log_safe import safe_text
from workers import supervisor

logger = logging.getLogger(__name__)


async def _schedule_director(ctx: TurnContext, committed: Committed) -> None:
    """Director, if enough in-game time elapsed and no run is in flight for the game."""
    state = committed.state
    if director_runs.is_running(ctx.request.game_id):
        logger.info("[CHAT] Director already in flight, not triggered")
        return
    # Re-read now: the previous turn's Director may have committed a plan since
    # the turn-start snapshot.
    async with ctx.pool.acquire() as sched_conn:
        schedule = await get_director_schedule(sched_conn, ctx.request.game_id)
    if should_run_director(
        state.time,
        schedule.last_time,
        schedule.game_duration,
        current_cycle=state.cycle,
        last_cycle=schedule.last_cycle,
    ):
        director_runs.start(ctx.request.game_id, run_director(
            pool=ctx.pool,
            game_id=ctx.request.game_id,
            current_cycle=state.cycle,
            current_time=state.time,
            session=ctx.session,
        ))
        logger.info(f"[CHAT] Director triggered at {state.time}")


def _enqueue_post_turn(ctx: TurnContext, narrated: Narrated, committed: Committed) -> None:
    """Resolver (always) + extractors (if triggered), after the game's earlier jobs."""
    triggers = narrated.narration.extraction_triggers
    if triggers:
        logger.info(f"[CHAT] Extraction triggers: {triggers}")
    event = TurnCommitted(
        game_id=ctx.request.game_id,
        previous_cycle=ctx.snapshot.current_cycle,
        cycle=committed.state.cycle,
        time=committed.state.time,
        user_message_id=committed.user_message_id,
        assistant_message_id=committed.assistant_message_id,
    )
    supervisor.enqueue(ctx.request.game_id, "post_turn", run_post_turn(
        ctx.pool,
        ctx.session,
        event,
        triggers=triggers or None,
        message_content=narrated.display_text,
        narrator_deltas=committed.narrator_deltas,
    ))


async def schedule_background(ctx: TurnContext, narrated: Narrated, committed: Committed) -> None:
    _enqueue_post_turn(ctx, narrated, committed)
    try:
        await _schedule_director(ctx, committed)
    except Exception as dir_err:
        logger.warning(f"[DIRECTOR] Trigger check failed: {safe_text(dir_err)}")
