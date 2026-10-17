"""Schedule step: background extraction and Director after the turn (fire and forget)."""

import asyncio
import logging

from pipeline.context import TurnContext
from pipeline.steps.commit import Committed
from pipeline.steps.narrate import Narrated
from repos.games import get_director_schedule
from services.director_service import run_director, should_run_director
from services.extraction import run_resolve_and_extract

logger = logging.getLogger(__name__)


def _schedule_extraction(ctx: TurnContext, narrated: Narrated, committed: Committed) -> None:
    """Resolver (always) + extractors (if triggered)."""
    triggers = narrated.narration.extraction_triggers
    if triggers:
        logger.info(f"[CHAT] Extraction triggers: {triggers}")
    asyncio.create_task(
        run_resolve_and_extract(
            pool=ctx.pool,
            game_id=ctx.request.game_id,
            trigger_cycle=ctx.snapshot.current_cycle,
            triggers=triggers or None,
            session=ctx.session,
            assistant_message_id=committed.assistant_message_id,
            message_content=narrated.display_text,
            narrator_deltas=committed.narrator_deltas,
        )
    )


async def _schedule_director(ctx: TurnContext, committed: Committed) -> None:
    """Director, if enough in-game time elapsed."""
    state = committed.state
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
        asyncio.create_task(
            run_director(
                pool=ctx.pool,
                game_id=ctx.request.game_id,
                current_cycle=state.cycle,
                current_time=state.time,
                session=ctx.session,
            )
        )
        logger.info(f"[CHAT] Director triggered at {state.time}")


async def schedule_background(ctx: TurnContext, narrated: Narrated, committed: Committed) -> None:
    _schedule_extraction(ctx, narrated, committed)
    try:
        await _schedule_director(ctx, committed)
    except Exception as dir_err:
        logger.warning(f"[DIRECTOR] Trigger check failed: {dir_err}")
