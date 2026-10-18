"""
LDVELH - Director Service
Background narrative planner that produces session-level guidance for the narrator.
Runs periodically based on in-game time elapsed: on_turn_committed, a post-turn hook. The run is split in three:
collect (services/director_context.py), call (call_director), apply (services/director_apply.py).
"""

import logging
from uuid import UUID

import asyncpg

from config import get_settings
from domain.turn import TurnCommitted
from llm.session import LLMSession, Purpose
from prompts.director_prompt import DIRECTOR_INTERVAL, DIRECTOR_SYSTEM_PROMPT
from repos.games import get_director_schedule
from schema.director import DirectorOutput
from services.director_apply import apply_director_plan
from services.director_context import DirectorContext, collect_director_context
from utils.json_utils import parse_json_response
from utils.log_safe import log_exception

logger = logging.getLogger(__name__)


def _parse_ig_hours(t: str) -> float:
    """Parse 'HHhMM' to fractional hours."""
    if not t or "h" not in t:
        return 0.0
    try:
        parts = t.split("h")
        return int(parts[0]) + int(parts[1] or "0") / 60
    except (ValueError, IndexError):
        return 0.0


def should_run_director(
    current_time: str,
    last_director_time: str | None,
    game_duration: str = "medium",
    current_cycle: int | None = None,
    last_cycle: int | None = None,
) -> bool:
    """Check if enough in-game time has elapsed since last Director run.

    When both cycles are known, elapsed time counts whole in-game days;
    otherwise it falls back to hour-of-day with a single day wrap.
    """
    interval = DIRECTOR_INTERVAL.get(game_duration, 6)

    if last_director_time is None:
        return True

    current_h = _parse_ig_hours(current_time)
    last_h = _parse_ig_hours(last_director_time)

    if current_cycle is not None and last_cycle is not None:
        elapsed = (current_cycle - last_cycle) * 24 + (current_h - last_h)
    else:
        # Handle day wrap (e.g., last=22h, current=03h → elapsed=5h)
        elapsed = current_h - last_h
        if elapsed < 0:
            elapsed += 24

    return elapsed >= interval


_SUBSTEPS = [  # JSON key -> status label sent once the key appears in the stream
    ("tension_level", "Tension narrative"),
    ("narrator_guidance", "Intentions PNJ"),
    ("planned_events", "Événements"),
    ("long_term_vision", "Vision globale"),
]


async def _stream_text(session: LLMSession, messages: list[dict], sink) -> str:
    """Stream the Director call, sending a status per sub-step as its JSON key appears."""
    full_json = ""
    await sink.send_status("director", "Tension narrative")
    sent_labels = {"Tension narrative"}
    stream = session.stream(
        Purpose.DIRECTOR, DIRECTOR_SYSTEM_PROMPT, messages, temperature=0.7, max_tokens=2000
    )
    async for chunk in stream:
        full_json += chunk
        for key, label in _SUBSTEPS:
            if label not in sent_labels and f'"{key}"' in full_json:
                sent_labels.add(label)
                await sink.send_status("director", label)
                logger.info(f"[DIRECTOR] Sub-step: {label}")
    return full_json


async def call_director(
    session: LLMSession, context: DirectorContext, sink=None,
) -> DirectorOutput | None:
    """Run the Director LLM on the context; None if it returned nothing usable.

    Streams with a status per sub-step when `sink` is given (init flow), one
    non-streaming completion otherwise (per-message trigger).
    """
    messages = [{"role": "user", "content": context.user_prompt()}]
    if sink:
        raw_result = parse_json_response(await _stream_text(session, messages, sink))
    else:
        call = await session.complete_text(
            Purpose.DIRECTOR, DIRECTOR_SYSTEM_PROMPT, messages, temperature=0.7, max_tokens=2000
        )
        raw_result = parse_json_response(call.value) if call.value else None
    if not raw_result:
        logger.warning("[DIRECTOR] LLM returned empty result")
        return None
    return DirectorOutput.model_validate(raw_result)


async def run_director(
    pool: asyncpg.Pool,
    game_id: UUID,
    current_cycle: int,
    current_time: str,
    session: LLMSession,
    sse_writer=None,
    *,
    source_message_id: UUID | None = None,
) -> dict | None:
    """Run the Director and store its plan: collect, call, apply (#96).

    No connection is held during the LLM call. With `source_message_id`, the plan is
    dropped if that message was deleted (rolled back) meanwhile.
    One run per game at a time: every run is a supervisor job of the game (workers/supervisor).
    """
    logger.info(f"[DIRECTOR] Starting for game {game_id} at cycle {current_cycle} {current_time}")

    context = None
    try:
        async with pool.acquire() as conn:
            context = await collect_director_context(conn, game_id, current_cycle, current_time)
        if context is None:
            logger.warning(f"[DIRECTOR] Game {game_id} not found")
            return None

        plan = await call_director(session, context, sse_writer)
        if plan is None:
            return None

        async with pool.acquire() as conn:
            stored = await apply_director_plan(
                conn, game_id, plan, cycle=current_cycle, ig_time=current_time,
                source_message_id=source_message_id,
            )
        if not stored:
            return None

        logger.info(
            f"[DIRECTOR] Plan stored for game {game_id}: "
            f"tension={plan.tension_level}, events={len(plan.planned_events)}, "
            f"arc_updates={len(plan.arc_updates)}"
        )
        return plan.model_dump()

    except Exception as e:
        log_exception(logger, logging.ERROR, f"[DIRECTOR] Failed for game {game_id}", e,
                      debug_detail=get_settings().log_prompts)
        if context is not None:
            logger.debug(f"[DIRECTOR] Context prompt was:\n{context.user_prompt()[:2000]}")
        return None


async def on_turn_committed(pool: asyncpg.Pool, session: LLMSession, event: TurnCommitted) -> None:
    """Post-turn hook: run the Director if enough in-game time elapsed since the last plan."""
    # Re-read now: the previous job of the game may have committed a plan since the turn.
    async with pool.acquire() as conn:
        schedule = await get_director_schedule(conn, event.game_id)
    if not should_run_director(event.time, schedule.last_time, schedule.game_duration,
                               current_cycle=event.cycle, last_cycle=schedule.last_cycle):
        logger.debug(f"[DIRECTOR] Interval not elapsed game={event.game_id} at {event.time}")
        return
    logger.info(f"[DIRECTOR] Triggered game={event.game_id} at {event.time}")
    await run_director(pool, event.game_id, event.cycle, event.time, session,
                       source_message_id=event.assistant_message_id)
