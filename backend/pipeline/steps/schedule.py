"""Schedule step: the post-turn job on the game's supervisor queue (#17).

The scheduled Director is a post-turn hook (services/hooks.py), run inside that job (#95).
"""

import logging

from domain.turn import TurnCommitted
from pipeline.context import TurnContext
from pipeline.post_turn import run_post_turn
from pipeline.steps.commit import Committed
from pipeline.steps.narrate import Narrated
from workers import supervisor

logger = logging.getLogger(__name__)


async def schedule_background(ctx: TurnContext, narrated: Narrated, committed: Committed) -> None:
    """Enqueue the turn's post_turn job: resolver (always), extractors (if triggered) and
    hooks, after the game's earlier jobs."""
    triggers = narrated.narration.extraction_triggers
    if triggers:
        logger.info(f"[CHAT] Extraction triggers: {triggers}")
    if ctx.turn_id is None:  # set by the load step: a committed turn always has one
        raise RuntimeError("committed turn without a turn id")
    event = TurnCommitted(
        game_id=ctx.request.game_id,
        previous_cycle=ctx.snapshot.current_cycle,
        cycle=committed.state.cycle,
        time=committed.state.time,
        user_message_id=committed.user_message_id,
        assistant_message_id=committed.assistant_message_id,
        turn_id=ctx.turn_id,
    )
    supervisor.enqueue(ctx.request.game_id, "post_turn", run_post_turn(
        ctx.pool,
        ctx.session.for_background(),  # same turn, its own call buffer (flushed by the job)
        event,
        triggers=triggers or None,
        message_content=narrated.display_text,
        narrator_deltas=committed.narrator_deltas,
    ))

