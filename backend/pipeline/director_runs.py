"""Initial Director run per game (#79): a supervisor job that the first turn waits for.

The initial Director may outlive its turn (client gone during world generation): the
first narration turn waits for it, bounded by what is left of its timeout, so it reads
the plan. It runs on the game's supervisor queue (workers/supervisor.py) like the
scheduled Director (a post-turn hook), so two Director runs of one game never overlap.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from workers import supervisor

logger = logging.getLogger(__name__)

# game -> (initial run, loop time a turn may wait until); forgotten when the run ends.
_initial: dict[UUID, tuple[asyncio.Task, float]] = {}


def start_initial(game_id: UUID, coro: Coroutine[Any, Any, Any], *,
                  wait_limit: float) -> asyncio.Task:
    """Enqueue `coro` as the game's initial Director; turns wait for it `wait_limit` s at most."""
    task = supervisor.enqueue(game_id, "director_initial", coro)
    entry = (task, asyncio.get_running_loop().time() + wait_limit)
    _initial[game_id] = entry
    task.add_done_callback(lambda _task: _forget(game_id, entry))
    return task


def _forget(game_id: UUID, entry: tuple[asyncio.Task, float]) -> None:
    if _initial.get(game_id) is entry:
        del _initial[game_id]


async def wait_for_initial(game_id: UUID) -> None:
    """Wait for the game's in-flight initial Director, within what is left of its limit."""
    entry = _initial.get(game_id)
    if entry is None:
        return
    task, wait_until = entry
    remaining = wait_until - asyncio.get_running_loop().time()
    if remaining <= 0:
        return
    logger.info(f"[DIRECTOR] Waiting for the initial run of game {game_id}")
    # asyncio.wait never cancels the run, even if this turn is cancelled meanwhile.
    await asyncio.wait({task}, timeout=remaining)
