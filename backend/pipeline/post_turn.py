"""Post-turn background job: resolver and extraction for a saved turn (#17).

Queued per game by the supervisor, so the job of turn N+1 runs after the one of turn N
instead of being skipped.
"""

import asyncpg

from domain.turn import TurnCommitted
from llm.session import LLMSession
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
    """Resolver (always) then the extractors (if triggered) for the committed turn."""
    await run_resolve_and_extract(
        pool,
        event.game_id,
        trigger_cycle=event.cycle,
        triggers=triggers,
        session=session,
        assistant_message_id=event.assistant_message_id,
        message_content=message_content,
        narrator_deltas=narrator_deltas,
    )
