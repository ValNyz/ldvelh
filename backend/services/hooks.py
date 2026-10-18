"""Post-turn hooks (#95): what runs after a committed turn, inside its post_turn job.

`on_turn_committed` subscribers run after every turn, each on its own: a failure is logged
and the next one still runs. `on_new_cycle` subscribers run when the turn started a new
in-game day, all in one transaction that holds the turn's assistant message (a rollback
deleting it waits for the commit; a turn already rolled back runs nothing).
Subscribers are registered once by services/subscribers.py, in registration order.
"""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

import asyncpg

from config import get_settings
from domain.turn import TurnCommitted
from llm.session import LLMSession
from repos import turns as turns_repo
from utils.log_safe import log_exception

logger = logging.getLogger(__name__)

TurnHook = Callable[[asyncpg.Pool, LLMSession, TurnCommitted], Awaitable[None]]
CycleHook = Callable[[asyncpg.Connection, UUID, int], Awaitable[None]]

_turn_hooks: list[TurnHook] = []
_cycle_hooks: list[CycleHook] = []


def _name(fn: Callable) -> str:
    return getattr(fn, "__qualname__", repr(fn))


def on_turn_committed(fn: TurnHook) -> TurnHook:
    """Register `fn` to run after every committed turn (decorator)."""
    if fn not in _turn_hooks:  # registered twice, it would run twice per turn
        _turn_hooks.append(fn)
    return fn


def on_new_cycle(fn: CycleHook) -> CycleHook:
    """Register `fn` to run when a turn starts a new in-game day (decorator)."""
    if fn not in _cycle_hooks:
        _cycle_hooks.append(fn)
    return fn


def reset() -> None:
    """Forget every subscriber (tests)."""
    _turn_hooks.clear()
    _cycle_hooks.clear()


async def run_turn_committed(pool: asyncpg.Pool, session: LLMSession,
                             event: TurnCommitted) -> None:
    """Each turn subscriber in turn; a failure is logged and does not stop the next ones."""
    for fn in list(_turn_hooks):
        try:
            await fn(pool, session, event)
        except Exception as exc:
            log_exception(logger, logging.ERROR,
                          f"[HOOKS] turn_committed subscriber {_name(fn)} failed "
                          f"game={event.game_id}", exc, debug_detail=get_settings().log_prompts)


async def run_new_cycle(pool: asyncpg.Pool, event: TurnCommitted) -> None:
    """The new-cycle subscribers in one transaction: one failure rolls them all back."""
    current: CycleHook | None = None
    phase = "hold_source_message"  # what failed when no subscriber is running
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                if not await turns_repo.hold_source_message(conn, event.assistant_message_id):
                    logger.info(f"[HOOKS] Turn rolled back, new_cycle skipped "
                                f"game={event.game_id} cycle={event.cycle}")
                    return
                for current in list(_cycle_hooks):
                    await current(conn, event.game_id, event.cycle)
                current, phase = None, "commit"  # every subscriber succeeded
        except Exception as exc:
            what = f"subscriber {_name(current)}" if current is not None else phase
            log_exception(logger, logging.ERROR,
                          f"[HOOKS] new_cycle {what} failed game={event.game_id}, "
                          "cycle hooks rolled back", exc,
                          debug_detail=get_settings().log_prompts)
