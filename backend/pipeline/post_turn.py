"""Post-turn background job: resolver, extraction, then the post-turn hooks (#17, #95).

Queued per game by the supervisor, so the job of turn N+1 runs after the one of turn N
instead of being skipped. The hooks (new-cycle work, scheduled Director) run after the
same turn's extraction, so the Director reads what it extracted.
"""

import asyncpg

from domain.turn import TurnCommitted
from llm.session import LLMSession
from services import hooks
from services.extraction import run_resolve_and_extract


async def run_post_turn(
    pool: asyncpg.Pool,
    session: LLMSession,
    event: TurnCommitted,
    *,
    triggers: list[str] | None,
    message_content: str,
    narrator_deltas: dict,
) -> None:
    """Resolver (always), the extractors (if triggered), then the hooks of the turn."""
    await run_resolve_and_extract(
        pool,
        event.game_id,
        trigger_cycle=event.cycle,
        triggers=triggers,
        session=session,
        assistant_message_id=event.assistant_message_id,
        message_content=message_content,
        narrator_deltas=narrator_deltas,
        turn_id=event.turn_id,
    )
    if event.new_cycle:
        await hooks.run_new_cycle(pool, event)
    await hooks.run_turn_committed(pool, session, event)
