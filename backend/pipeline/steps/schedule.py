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


def _enqueue_post_turn(ctx: TurnContext, narrated: Narrated, committed: Committed) -> None:
    """Resolver (always), extractors (if triggered) and hooks, after the game's earlier jobs."""
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
